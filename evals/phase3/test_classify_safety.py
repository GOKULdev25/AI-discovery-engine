"""EV-P3-08, 09, 10 — the three safety properties around what actually
reaches an LLM and what's allowed to come back: malformed output is
contained to its own batch, out-of-enum labels never reach the warehouse,
and text the local gate already resolved never leaves the machine at all.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.ai.providers import fake
from app.pipeline import classify
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.registry import eval_case

_PROTOTYPES_CONTENT = """\
keep:
  - "The app keeps crashing every time I open it, this really needs to be fixed."
drop:
  - "Buy cheap watches now at this link, limited time offer, click here!"
"""


@eval_case(
    "EV-P3-08",
    proves="Malformed JSON from the provider produces a contained failure: the batch stays ambiguous, the call doesn't raise, the run continues",
    source="EVAL.md §6.5",
    severity="MAJOR",
    tags=["phase:P3"],
)
async def ev_p3_08():
    docs = [{"doc_id": f"d{i}", "text": f"a genuinely unique review body {i} about the product"} for i in range(3)]
    with tempfile.TemporaryDirectory(prefix="ev-p308-") as tmp:
        prototypes_path = Path(tmp) / "prototypes.yaml"
        prototypes_path.write_text(_PROTOTYPES_CONTENT, encoding="utf-8")
        app_sqlite = Path(tmp) / "app.sqlite"
        # Not a JSON array at all — the top-level shape classify.py requires.
        provider = fake.gemini_like(script=[{"this": "is not a decisions array"}])
        async with sq.app_db(app_sqlite) as conn:
            resolved = await classify.classify_batch(conn, [provider], prototypes_path, docs)
        assert resolved == [], "a malformed top-level response must resolve nothing, leaving the batch ambiguous"


@eval_case(
    "EV-P3-09",
    proves="No out-of-enum label ever reaches the warehouse, even when the provider returns one",
    source="EVAL.md §6.5",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_09():
    docs = [
        {"doc_id": "good", "text": "a genuinely unique review body about a specific product problem"},
        {"doc_id": "bad-label", "text": "another genuinely unique review body with a different complaint"},
        {"doc_id": "hallucinated-id", "text": "yet another genuinely unique review body, third one"},
    ]
    with tempfile.TemporaryDirectory(prefix="ev-p309-") as tmp:
        prototypes_path = Path(tmp) / "prototypes.yaml"
        prototypes_path.write_text(_PROTOTYPES_CONTENT, encoding="utf-8")
        app_sqlite = Path(tmp) / "app.sqlite"
        # A well-formed array, but with an out-of-enum decision and a
        # doc_id that was never part of the batch — both must be rejected
        # independently, without poisoning the one genuinely valid entry.
        provider = fake.gemini_like(script=[[
            {"doc_id": "good", "decision": "keep"},
            {"doc_id": "bad-label", "decision": "delete"},
            {"doc_id": "not-in-the-batch", "decision": "keep"},
        ]])
        async with sq.app_db(app_sqlite) as conn:
            resolved = await classify.classify_batch(conn, [provider], prototypes_path, docs)

        resolved_ids = {doc_id for doc_id, _band, _score in resolved}
        assert resolved_ids == {"good"}, f"only the schema-conformant entry should resolve, got {resolved_ids}"
        bands = {doc_id: band for doc_id, band, _score in resolved}
        assert bands["good"] in ("keep", "drop"), "every resolved band must be a valid enum value"


@eval_case(
    "EV-P3-10",
    proves="Documents the local gate already decided (keep or drop) never appear in an LLM request body — only the ambiguous band does",
    source="EVAL.md §6.5",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_10():
    keep_text = "SENTINEL-KEEP: this exact text must never reach a provider prompt"
    drop_text = "SENTINEL-DROP: this exact text must never reach a provider prompt either"
    ambiguous_text = "SENTINEL-AMBIGUOUS: this is the only text a provider should ever see"

    with tempfile.TemporaryDirectory(prefix="ev-p310-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p310")
        project_dir = resolver.project_dir(config.id)
        prototypes_path = resolver.gate_prototypes_path(config.id)
        app_sqlite = settings.app_sqlite_path

        try:
            committer = await dk.get_committer(project_dir)
            now = "2026-08-29T00:00:00Z"
            rows = [
                {
                    "doc_id": doc_id, "project_id": config.id, "batch_id": "b", "source": "fixture",
                    "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": now,
                    "lane": "api", "extractor_version": "v", "raw": {}, "text": text,
                }
                for doc_id, text in [("keep-doc", keep_text), ("drop-doc", drop_text), ("ambiguous-doc", ambiguous_text)]
            ]
            await committer.commit_rows(rows)
            await committer.upsert_enrichment([
                {"doc_id": "keep-doc", "gate_band": "keep", "gate_score": 0.9},
                {"doc_id": "drop-doc", "gate_band": "drop", "gate_score": -0.9},
                {"doc_id": "ambiguous-doc", "gate_band": "ambiguous", "gate_score": 0.0},
            ])

            provider = fake.gemini_like(script=[[{"doc_id": "ambiguous-doc", "decision": "keep"}]])
            async with sq.app_db(app_sqlite) as conn:
                resolved_count = await classify.classify_pending_documents(
                    committer, conn, [provider], prototypes_path
                )

            assert resolved_count == 1
            all_prompts = " ".join(provider.calls)
            assert keep_text not in all_prompts, "an already-'keep' document's text reached a provider prompt"
            assert drop_text not in all_prompts, "an already-'drop' document's text reached a provider prompt — a cost and privacy violation"
            assert ambiguous_text in all_prompts, "the actually-ambiguous document should have been the one sent"
        finally:
            await dk.forget_committer(project_dir)
