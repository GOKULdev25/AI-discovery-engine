"""EV-P5-10, 11 — batch narrowing actually narrows retrieval, and a
study's line of questioning survives a restart (chat history persists in
`ops.sqlite`, not memory)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.chat.retrieval import hybrid_retrieve
from app.chat.service import ask
from app.ai.providers import fake
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.phase5._helpers import doc_row, seed_and_index
from evals.registry import eval_case


@eval_case(
    "EV-P5-10",
    proves="Scoping to one batch excludes other batches' documents from retrieval",
    source="A§12",
    severity="MAJOR",
    tags=["phase:P5"],
)
async def ev_p5_10():
    with tempfile.TemporaryDirectory(prefix="ev-p510-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p510")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            async with sq.ops_db(project_dir) as ops_conn:
                await seed_and_index(committer, ops_conn, [
                    doc_row("a1", config.id, "The camera app keeps crashing on startup.", batch_id="batch-a"),
                ])
                await seed_and_index(committer, ops_conn, [
                    doc_row("b1", config.id, "The camera app keeps crashing on startup too.", batch_id="batch-b"),
                ])
                reader = await dk.get_reader(project_dir)

                scoped = await hybrid_retrieve(ops_conn, reader, "camera app crashing", batch_id="batch-a")
                unscoped = await hybrid_retrieve(ops_conn, reader, "camera app crashing")

            scoped_ids = {d["doc_id"] for d in scoped}
            unscoped_ids = {d["doc_id"] for d in unscoped}
            assert "b1" not in scoped_ids, "batch-a scoping must exclude batch-b's document"
            assert "a1" in scoped_ids
            assert {"a1", "b1"}.issubset(unscoped_ids), "unscoped retrieval must see both batches"
        finally:
            await dk.forget_committer(project_dir)


@eval_case(
    "EV-P5-11",
    proves="Chat history persists in ops.sqlite and reloads after a restart",
    source="A§12",
    severity="MAJOR",
    tags=["phase:P5"],
)
async def ev_p5_11():
    with tempfile.TemporaryDirectory(prefix="ev-p511-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p511")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            async with sq.ops_db(project_dir) as ops_conn:
                await seed_and_index(committer, ops_conn, [
                    doc_row("d1", config.id, "The app crashes every time I open the camera."),
                ])
                reader = await dk.get_reader(project_dir)
                provider = fake.groq_like(script=[{"type": "insufficient_evidence", "text": "Not enough data.", "citations": []}])
                async with sq.app_db(Path(tmp) / "app.sqlite") as app_conn:
                    await ask(ops_conn, app_conn, reader, [provider], config.id, "What crashes are reported?")

            # "Restart": a brand new ops.sqlite connection, exactly what a
            # killed-and-relaunched backend would open.
            async with sq.ops_db(project_dir) as ops_conn2:
                cur = await ops_conn2.execute(
                    "SELECT role, content FROM chat_messages WHERE project_id = ? ORDER BY created_at", (config.id,)
                )
                rows = await cur.fetchall()

            assert len(rows) == 2, f"expected the user question and the assistant reply to survive, got {len(rows)} row(s)"
            assert rows[0]["role"] == "user" and rows[0]["content"] == "What crashes are reported?"
            assert rows[1]["role"] == "assistant"
        finally:
            await dk.forget_committer(project_dir)
