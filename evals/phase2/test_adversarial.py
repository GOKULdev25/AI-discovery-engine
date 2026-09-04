"""EV-P2-13 — an adversarial text corpus survives the full
staging -> commit -> enrich pipeline: no crash, no silent data loss, no
row dropped. Every one of these shapes is something a real scraped
review/comment can actually contain (huge bodies, zero-width joiners,
RTL override attacks, embedded markup, malformed-encoding surrogates)
— this is not a hypothetical fuzz corpus.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from app.pipeline import enrich_local
from app.pipeline.commit import drain_staging
from app.pipeline.enrich import enrich_pending_documents
from app.pipeline.normalize import normalize_row
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.corpora.adversarial import PARSER_ADVERSARIAL_TEXTS
from evals.harness import make_settings
from evals.registry import eval_case

_NOW = "2026-08-29T00:00:00Z"

_ADVERSARIAL_TEXTS = PARSER_ADVERSARIAL_TEXTS


def _row(doc_id: str, text: str) -> dict:
    return {
        "doc_id": doc_id, "project_id": "p", "batch_id": "b", "source": "fixture",
        "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": _NOW,
        "lane": "api", "extractor_version": "v", "raw": {"note": text[:20]}, "text": text,
    }


@eval_case(
    "EV-P2-13",
    proves="An adversarial text corpus (huge bodies, zero-width chars, RTL override, embedded HTML, SQL-special chars, lone surrogates) survives commit and enrichment with no crash and no row dropped",
    source="IP§2",
    severity="BLOCKER",
    tags=["phase:P2"],
)
async def ev_p2_13():
    # Pay the ~10s fastembed ONNX model load here, outside the timed
    # section below — in production that's paid once at API startup
    # (main.py's warmup_enrichment_models()), never per document.
    await enrich_local.warmup()
    with tempfile.TemporaryDirectory(prefix="ev-p213-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p213")
        project_dir = resolver.project_dir(config.id)
        try:
            async with sq.ops_db(project_dir) as ops_conn:
                for doc_id, text in _ADVERSARIAL_TEXTS.items():
                    # normalize_row() is what Ctx.emit() runs on every
                    # connector's output before it ever reaches staging —
                    # go through the same funnel here, not a shortcut.
                    row = normalize_row(_row(doc_id, text))
                    # Round-trips through JSON exactly like Ctx.emit() does —
                    # this is where a lone surrogate gets its one legitimate
                    # escape-and-restore before reaching the commit path.
                    row_json = json.dumps(row)
                    json.loads(row_json)  # must not raise
                    await ops_conn.execute(
                        "INSERT INTO staging_docs (doc_id, project_id, batch_id, row_json, created_at) VALUES (?,?,?,?,?)",
                        (doc_id, config.id, "b1", row_json, _NOW),
                    )
                await ops_conn.commit()

                committer = await dk.get_committer(project_dir)
                drained = await drain_staging(ops_conn, committer)
                assert drained == len(_ADVERSARIAL_TEXTS), (
                    f"expected all {len(_ADVERSARIAL_TEXTS)} adversarial rows to commit, got {drained}"
                )

                # VADER's polarity_scores is quadratic in input length
                # (measured: 57k chars -> 17.4s) — one long real document
                # must never be allowed to stall the whole batch's
                # enrichment for tens of seconds (EV-P2-13).
                t0 = time.monotonic()
                await enrich_pending_documents(project_dir, committer)
                elapsed = time.monotonic() - t0
                assert elapsed < 10, (
                    f"enrichment of {len(_ADVERSARIAL_TEXTS)} docs (one 57k chars) took {elapsed:.1f}s — "
                    "a quadratic-cost library call on long text is likely uncapped again"
                )

                reader = await dk.get_reader(project_dir)
                doc_count = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                assert doc_count == len(_ADVERSARIAL_TEXTS), "no adversarial row should be silently dropped"

                enrichment_count = reader.execute("SELECT COUNT(*) FROM enrichment").fetchone()[0]
                assert enrichment_count == len(_ADVERSARIAL_TEXTS), "every adversarial row must still get enriched"

                # The huge body and the SQL-special-char body must survive
                # byte-for-byte through normalize_row() (mod .strip()/NFC,
                # which is normalize_row's own contract) — the whole point
                # of literal-SQL escaping in the committer is that content,
                # not just row count, comes back intact.
                stored = dict(reader.execute("SELECT doc_id, text FROM documents").fetchall())
                expected = {
                    doc_id: normalize_row(_row(doc_id, text))["text"]
                    for doc_id, text in _ADVERSARIAL_TEXTS.items()
                }
                assert stored["huge"] == expected["huge"]
                assert stored["sql-special"] == expected["sql-special"]
                assert stored["embedded-html"] == expected["embedded-html"]
                assert "\ud800" not in stored["lone-surrogate"], (
                    "the lone surrogate must be sanitized before it reaches the warehouse, not passed through"
                )

                # The "huge" doc's highly-periodic content overflows the
                # third-party simhash library's own weighting code — it
                # must degrade to a null simhash for that one row, not
                # crash enrichment for the whole batch it shares with
                # every other adversarial row here.
                simhash_by_id = dict(reader.execute("SELECT doc_id, simhash FROM enrichment").fetchall())
                assert simhash_by_id["huge"] is None
                assert simhash_by_id["mixed-script"] is not None, "a normal document's simhash must not be collateral damage"
        finally:
            await dk.forget_committer(project_dir)
