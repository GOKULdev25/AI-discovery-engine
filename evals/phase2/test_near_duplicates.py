"""EV-P2-05 — near-duplicates are a flag, never a delete (dedup.py's
whole reason for existing as a signal separate from doc_id identity)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.pipeline import dedup
from app.pipeline.commit import drain_staging
from app.pipeline.enrich import enrich_pending_documents
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.registry import eval_case

_NOW = "2026-08-29T00:00:00Z"


def _row(doc_id: str, text: str) -> dict:
    return {
        "doc_id": doc_id, "project_id": "p", "batch_id": "b", "source": "fixture",
        "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": _NOW,
        "lane": "api", "extractor_version": "v", "raw": {}, "text": text,
    }


@eval_case(
    "EV-P2-05",
    proves="Near-duplicate documents are flagged via simhash but never deleted — both rows survive the full commit+enrich pipeline",
    source="IP§2.2",
    severity="MAJOR",
    tags=["phase:P2"],
)
async def ev_p2_05():
    docs = {
        "dup-a": "This app is absolutely amazing and I love it every single day, best purchase ever made in years.",
        "dup-b": "This app is absolutely amazing and I love it every single day, best purchase ever made in years, truly.",
        "distinct-c": "Customer support ignored my refund request for three weeks straight.",
    }

    with tempfile.TemporaryDirectory(prefix="ev-p205-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p205")
        project_dir = resolver.project_dir(config.id)
        try:
            async with sq.ops_db(project_dir) as ops_conn:
                for doc_id, text in docs.items():
                    row = _row(doc_id, text)
                    await ops_conn.execute(
                        "INSERT INTO staging_docs (doc_id, project_id, batch_id, row_json, created_at) VALUES (?,?,?,?,?)",
                        (doc_id, config.id, "b1", json.dumps(row), _NOW),
                    )
                await ops_conn.commit()

                committer = await dk.get_committer(project_dir)
                drained = await drain_staging(ops_conn, committer)
                assert drained == 3

                await enrich_pending_documents(project_dir, committer)

                reader = await dk.get_reader(project_dir)

                # The core guarantee: near-duplicate detection never removes rows.
                doc_count = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                assert doc_count == 3, "near-duplicate handling must never delete documents"

                fingerprints = reader.execute(
                    "SELECT doc_id, simhash FROM enrichment"
                ).fetchall()
                assert len(fingerprints) == 3
                simhash_by_id = dict(fingerprints)
                assert all(simhash_by_id.values()), "every non-empty document should get a simhash"

                pairs = dedup.find_near_duplicates(list(fingerprints))
                pair_ids = {frozenset((a, b)) for a, b, _dist in pairs}
                assert frozenset(("dup-a", "dup-b")) in pair_ids, (
                    f"the near-duplicate pair was not flagged: {pairs}"
                )
                assert frozenset(("dup-a", "distinct-c")) not in pair_ids
                assert frozenset(("dup-b", "distinct-c")) not in pair_ids
        finally:
            await dk.forget_committer(project_dir)
