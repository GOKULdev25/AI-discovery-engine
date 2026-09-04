"""`POST /projects/{p}/chat` + history (A§12, A§13). Scoped to the
project by default, narrowable to one batch (`batch_id` in the request
body) exactly like the dashboard's analytics endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai.providers.factory import build_chat_providers
from app.api.deps import settings_dep
from app.chat.service import ask
from app.config import Settings
from app.http_client import new_http_client
from app.projects.resolver import get_resolver
from app.store import duckdb as dk
from app.store import sqlite as sq

router = APIRouter(prefix="/projects/{project_id}/chat", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    batch_id: str | None = None
    # Lets the dashboard's chat pane answer over exactly the slice its
    # charts are showing, instead of silently describing the whole project
    # while the chart beside it shows one source. Scoping only ever
    # narrows, so cross-project isolation (EV-P5-09) is unaffected.
    source: str | None = None


class ChatResponse(BaseModel):
    type: str
    text: str
    citations: list[str]
    caveats: dict[str, bool]
    evidence_count: int


class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    citations: list[str] | None
    created_at: str


@router.post("", response_model=ChatResponse)
async def post_chat(project_id: str, body: ChatRequest, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)

    async with new_http_client() as http_client:
        providers = build_chat_providers(settings, http_client)
        async with sq.ops_db(project_dir) as ops_conn, sq.app_db(settings.app_sqlite_path) as app_conn:
            result = await ask(
                ops_conn,
                app_conn,
                reader,
                providers,
                project_id,
                body.question,
                batch_id=body.batch_id,
                source=body.source,
            )
    return result


@router.get("", response_model=list[ChatMessage])
async def get_chat_history(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    clause = "project_id = ?"
    params: list[object] = [project_id]
    if batch_id:
        clause += " AND batch_id = ?"
        params.append(batch_id)
    async with sq.ops_db(project_dir) as ops_conn:
        cur = await ops_conn.execute(
            f"SELECT id, role, content, citations, created_at FROM chat_messages WHERE {clause} ORDER BY created_at",
            params,
        )
        rows = await cur.fetchall()
    return [
        ChatMessage(
            id=r["id"], role=r["role"], content=r["content"],
            citations=json.loads(r["citations"]) if r["citations"] else None,
            created_at=r["created_at"],
        )
        for r in rows
    ]
