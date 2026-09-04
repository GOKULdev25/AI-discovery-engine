"""EV-P2-07, 08 — nothing is inferred, and the raw author handle never
reaches the warehouse (the entire point of `author_hash`)."""

from __future__ import annotations

from evals.harness import api_client, temp_project, wait_for_batch_done
from evals.registry import eval_case


@eval_case(
    "EV-P2-07",
    proves="Nothing is inferred: no row has authored_at silently backfilled from captured_at",
    source="A§8",
    severity="BLOCKER",
    tags=["phase:P2"],
)
async def ev_p2_07():
    async with temp_project("p2-07") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        async with api_client(settings) as client:
            resp = await client.post(
                f"/projects/{project_id}/batches",
                json={"urls": ["fixture://run?count=5&latency_ms=0"]},  # fixture never sets authored_at
            )
            await wait_for_batch_done(client, project_id, resp.json()["batch_id"])

        from app.store import duckdb as dk

        reader = await dk.get_reader(project_dir)
        rows = reader.execute("SELECT authored_at, captured_at FROM documents").fetchall()
        assert rows, "expected at least one document"
        for authored_at, captured_at in rows:
            assert authored_at is None, (
                f"authored_at was populated ({authored_at!r}) for a source that never provided one"
            )
            assert captured_at is not None  # captured_at IS always required — this isn't the null one


@eval_case(
    "EV-P2-08",
    proves="The raw author handle never reaches the warehouse — author_hash only, everywhere",
    source="IP§2.1",
    severity="BLOCKER",
    tags=["phase:P2"],
)
async def ev_p2_08():
    async with temp_project("p2-08") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        async with api_client(settings) as client:
            resp = await client.post(
                f"/projects/{project_id}/batches",
                json={"urls": ["fixture://run?count=5&latency_ms=0&link=probe"]},
            )
            await wait_for_batch_done(client, project_id, resp.json()["batch_id"])

        from app.store import duckdb as dk

        reader = await dk.get_reader(project_dir)
        rows = reader.execute(
            "SELECT doc_id, author_hash, text, raw, source_url FROM documents"
        ).fetchall()
        assert rows
        for doc_id, author_hash, text, raw, source_url in rows:
            assert author_hash is not None
            # The fixture connector's raw author id is "author-{i}" — the
            # plaintext must never appear anywhere on the row, only its hash.
            for field_name, value in [("text", text), ("raw", raw), ("source_url", source_url)]:
                assert "author-" not in (value or ""), (
                    f"a plaintext author handle leaked into {field_name} on {doc_id}: {value!r}"
                )
