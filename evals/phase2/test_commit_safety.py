"""EV-P2-03, 09 — the single-writer commit path under concurrency, and
its crash-safety (A§9 🔒, the most likely way to corrupt the warehouse)."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.pipeline import commit as pipeline_commit
from app.pipeline.ids import compute_doc_id
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.registry import eval_case


def _row(doc_id: str) -> dict:
    return {
        "doc_id": doc_id, "project_id": "p", "batch_id": "b", "source": "fixture",
        "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": "2026-08-29 00:00:00",
        "lane": "api", "extractor_version": "v", "raw": {}, "text": f"text {doc_id}",
    }


@eval_case(
    "EV-P2-03",
    proves="The single-writer committer holds under concurrency: 8 concurrent commit_rows() calls, zero lock errors, exact count 🔒",
    source="A§9",
    severity="BLOCKER",
    tags=["phase:P2"],
)
async def ev_p2_03():
    with tempfile.TemporaryDirectory(prefix="ev-p203-") as tmp:
        proj = Path(tmp)
        committer = await dk.get_committer(proj)
        try:
            n_workers = 8
            rows_per_worker = 50
            # Deliberately overlapping doc_id ranges across "workers" —
            # this also exercises the ON CONFLICT DO NOTHING idempotency
            # under real concurrent contention, not just sequential reuse.
            errors = []

            async def worker(worker_idx: int) -> None:
                try:
                    rows = [_row(f"doc-{(worker_idx * 40 + i) % 300}") for i in range(rows_per_worker)]
                    await committer.commit_rows(rows)
                except Exception as exc:  # the eval, not the product — any exception here is the failure
                    errors.append(exc)

            await asyncio.gather(*(worker(i) for i in range(n_workers)))
            assert not errors, f"concurrent commit_rows() raised: {errors}"

            reader = await dk.get_reader(proj)
            total = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            distinct = reader.execute("SELECT COUNT(DISTINCT doc_id) FROM documents").fetchone()[0]
            assert total == distinct == 300, f"expected exactly 300 distinct rows, got total={total} distinct={distinct}"
        finally:
            await dk.forget_committer(proj)


@eval_case(
    "EV-P2-09",
    proves="The commit path survives a crash mid-flush: no partial batch and no duplicate on the next drain",
    source="A§9",
    severity="BLOCKER",
    tags=["phase:P2"],
)
async def ev_p2_09():
    settings = None
    with tempfile.TemporaryDirectory(prefix="ev-p209-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p209")
        project_dir = resolver.project_dir(config.id)
        try:
            async with sq.ops_db(project_dir) as ops_conn:
                now = "2026-08-29T00:00:00Z"
                rows = [_row(f"crash-doc-{i}") for i in range(10)]
                for i, row in enumerate(rows):
                    await ops_conn.execute(
                        "INSERT INTO staging_docs (doc_id, project_id, batch_id, row_json, created_at) VALUES (?,?,?,?,?)",
                        (row["doc_id"], config.id, "b1", json.dumps(row), now),
                    )
                await ops_conn.commit()

                committer = await dk.get_committer(project_dir)
                # Simulate "the process crashed right after commit_rows()
                # returned, before staging_docs could be marked
                # committed=1" — the exact window pipeline/commit.py's
                # docstring names as the crash-safety property under test.
                await committer.commit_rows(rows)

                reader = await dk.get_reader(project_dir)
                mid_crash_count = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                assert mid_crash_count == 10

                # "Restart": staging still shows committed=0 for all 10 —
                # the next drain (as main.py's lifespan/engine would run)
                # must not duplicate what's already durably committed.
                drained = await pipeline_commit.drain_staging(ops_conn, committer)
                assert drained == 10, "drain should still process the rows staging thinks are pending"

                final_count = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                distinct_count = reader.execute("SELECT COUNT(DISTINCT doc_id) FROM documents").fetchone()[0]
                assert final_count == 10, f"expected no duplicate rows after re-drain, got {final_count}"
                assert distinct_count == 10

                cur = await ops_conn.execute("SELECT COUNT(*) c FROM staging_docs WHERE committed = 1")
                row = await cur.fetchone()
                assert row["c"] == 10, "the re-drain must still mark staging rows committed"
        finally:
            await dk.forget_committer(project_dir)
