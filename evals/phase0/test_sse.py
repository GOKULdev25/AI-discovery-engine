"""EV-P0-04, 08 — live per-link SSE progress and replay-on-reconnect."""

from __future__ import annotations

import json

from evals.harness import api_client, temp_project
from evals.registry import eval_case


def _parse_sse(raw: str) -> list[dict]:
    events = []
    current: dict = {}
    for line in raw.splitlines():
        if line.startswith(":"):
            continue
        if line == "":
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith("id: "):
            current["id"] = int(line[4:])
        elif line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
    if current:
        events.append(current)
    return events


@eval_case(
    "EV-P0-04",
    proves="A batch of 50 fixture:// links shows live per-link progress over SSE",
    source="IP§0.6",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_04():
    async with temp_project("p0-04") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            urls = [f"fixture://run?count=2&latency_ms=1&link={i}" for i in range(50)]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            batch_id = resp.json()["batch_id"]
            link_ids = {l["link_id"] for l in resp.json()["links"]}
            assert len(link_ids) == 50

            raw_chunks = []
            async with client.stream(
                "GET", f"/projects/{project_id}/batches/{batch_id}/stream", timeout=15
            ) as stream:
                async for chunk in stream.aiter_text():
                    raw_chunks.append(chunk)
                    if '"event": "batch.done"' in chunk or "batch.done" in chunk:
                        break

            events = _parse_sse("".join(raw_chunks))
            terminal_seen = {
                e["data"]["link_id"] for e in events
                if e.get("event") == "link.status" and e["data"].get("status") in ("done", "failed")
            }
            assert terminal_seen == link_ids, (
                f"missing terminal link.status for {link_ids - terminal_seen}"
            )
            assert any(e.get("event") == "batch.done" for e in events)


@eval_case(
    "EV-P0-08",
    proves="A dropped SSE stream replays missed events from the events table on reconnect",
    source="IP§0.6",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_08():
    async with temp_project("p0-08") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            urls = [f"fixture://run?count=20&latency_ms=10&link={i}" for i in range(4)]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            batch_id = resp.json()["batch_id"]

            # httpx's ASGI test transport buffers the whole response rather
            # than delivering it incrementally, so a real batch finishes
            # before this first read ever returns — there's no genuine
            # "disconnect mid-stream" to simulate here. Instead: read
            # everything once, then reconnect from a real midpoint id so
            # the replay path (not the live-wait path) is what's exercised
            # — reconnecting from the *last* id (batch.done itself) would
            # have nothing left to replay and hang waiting on events that
            # already happened.
            first_pass = []
            async with client.stream(
                "GET", f"/projects/{project_id}/batches/{batch_id}/stream", timeout=15
            ) as stream:
                async for chunk in stream.aiter_text():
                    first_pass.append(chunk)
                    if "batch.done" in chunk:
                        break

            seen_before = _parse_sse("".join(first_pass))
            assert len(seen_before) >= 2, "need at least 2 events to pick a real midpoint"
            midpoint = seen_before[len(seen_before) // 2]["id"]

            reconnect_chunks = []
            async with client.stream(
                "GET", f"/projects/{project_id}/batches/{batch_id}/stream",
                params={"since": midpoint}, timeout=15,
            ) as stream:
                async for chunk in stream.aiter_text():
                    reconnect_chunks.append(chunk)
                    if "batch.done" in chunk:
                        break

            replayed = _parse_sse("".join(reconnect_chunks))
            assert replayed, "reconnect produced no events at all"
            assert all(e["id"] > midpoint for e in replayed if "id" in e), (
                "replay included an event already seen before the disconnect"
            )
            assert any(e.get("event") == "batch.done" for e in replayed)
