"""Batch submission, status, per-link detail, retry, and the SSE progress
stream (A§13, IP§0.6). `POST /batches` returns immediately; workers claim
and dispatch in the background (EV-P0-14)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import settings_dep
from app.config import Settings
from app.jobs.engine import BatchTooLarge, retry_batch, submit_batch
from app.jobs.events import get_event_bus
from app.projects.resolver import get_resolver
from app.store import sqlite as sq

router = APIRouter(prefix="/projects/{project_id}/batches", tags=["batches"])


class SubmitBatchRequest(BaseModel):
    urls: list[str]


class LinkSummary(BaseModel):
    link_id: str
    url: str
    status: str
    failure_code: str | None = None
    job_count: int | None = None


class SubmitBatchResponse(BaseModel):
    batch_id: str
    links: list[LinkSummary]


class BatchSummary(BaseModel):
    id: str
    status: str
    link_count: int
    created_at: str
    updated_at: str
    counts: dict[str, int]


@router.post("", response_model=SubmitBatchResponse, status_code=202)
async def create_batch(project_id: str, body: SubmitBatchRequest, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    if not resolver.exists(project_id):
        raise HTTPException(404, "project not found")
    try:
        batch_id, links = await submit_batch(settings, project_id, body.urls)
    except BatchTooLarge as exc:
        raise HTTPException(422, f"batch of {exc.count} links exceeds the {exc.limit}-link limit; split into smaller batches")
    return SubmitBatchResponse(batch_id=batch_id, links=[LinkSummary(**l) for l in links])


@router.get("", response_model=list[BatchSummary])
async def list_batches(
    project_id: str, limit: int = 25, settings: Settings = Depends(settings_dep)
):
    """This project's batches, newest first — the run history.

    Without this, a batch's per-link outcomes were only ever visible in the
    browser tab that submitted it: a reload lost them, and with them the typed
    failure reasons P§8 promises stay visible. The rows themselves have always
    been durable in `ops.sqlite`; only a way to list them was missing.
    """
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    limit = max(1, min(limit, 200))

    async with sq.ops_db(project_dir) as ops_conn:
        cur = await ops_conn.execute(
            """SELECT id, status, link_count, created_at, updated_at FROM batches
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        batches = [dict(r) for r in await cur.fetchall()]
        if not batches:
            return []

        # One grouped query for every batch on the page rather than one per
        # batch — the per-status counts are what make the list scannable
        # ("2 failed" without opening it).
        placeholders = ",".join("?" for _ in batches)
        cur = await ops_conn.execute(
            f"""SELECT batch_id, status, COUNT(*) c FROM links
                WHERE batch_id IN ({placeholders}) GROUP BY batch_id, status""",
            [b["id"] for b in batches],
        )
        counts: dict[str, dict[str, int]] = {}
        for row in await cur.fetchall():
            counts.setdefault(row["batch_id"], {})[row["status"]] = row["c"]

    return [BatchSummary(**b, counts=counts.get(b["id"], {})) for b in batches]


@router.get("/{batch_id}")
async def get_batch(project_id: str, batch_id: str, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    async with sq.ops_db(project_dir) as ops_conn:
        cur = await ops_conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(404, "batch not found")
        cur = await ops_conn.execute(
            "SELECT status, COUNT(*) c FROM links WHERE batch_id = ? GROUP BY status", (batch_id,)
        )
        counts = {r["status"]: r["c"] for r in await cur.fetchall()}
    return {"id": row["id"], "status": row["status"], "link_count": row["link_count"], "counts": counts}


@router.get("/{batch_id}/links", response_model=list[dict])
async def get_batch_links(project_id: str, batch_id: str, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    async with sq.ops_db(project_dir) as ops_conn:
        cur = await ops_conn.execute(
            "SELECT id, url, connector_id, status, failure_code, retryable, doc_count FROM links WHERE batch_id = ? ORDER BY created_at",
            (batch_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.post("/{batch_id}/retry")
async def retry(project_id: str, batch_id: str, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    if not resolver.exists(project_id):
        raise HTTPException(404, "project not found")
    retried = await retry_batch(settings, project_id, batch_id)
    return {"retried": retried}


def _format_sse(event_id: int | None, event_type: str, data: dict) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


@router.get("/{batch_id}/stream")
async def stream_batch(
    project_id: str, batch_id: str, request: Request, settings: Settings = Depends(settings_dep)
):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    bus = get_event_bus()

    last_id_header = request.headers.get("last-event-id")
    since = int(request.query_params.get("since", last_id_header or 0) or 0)

    async def generator():
        async with sq.ops_db(project_dir) as ops_conn:
            replayed = await bus.replay_since(ops_conn, batch_id, since)
            for ev in replayed:
                yield _format_sse(ev["id"], ev["event"], ev["data"])
                if ev["event"] == "batch.done":
                    return

            queue = bus.subscribe(batch_id)
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=settings.sse_heartbeat_seconds)
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    yield _format_sse(ev["id"], ev["event"], ev["data"])
                    if ev["event"] == "batch.done":
                        return
            finally:
                bus.unsubscribe(batch_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
