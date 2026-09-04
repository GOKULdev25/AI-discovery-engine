"""EV-P5-04 — 100% of cited doc_ids resolve to rows actually retrieved
for the turn. A hallucinated citation is the worst possible failure in
this system (it looks exactly like rigour) — never quarantined, never
softened (EVAL.md §10.3)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.ai.providers import fake
from app.chat import grounding
from app.chat.service import ask
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.phase5._helpers import doc_row, seed_and_index
from evals.registry import eval_case


@eval_case(
    "EV-P5-04",
    proves="100% of cited doc_ids resolve to rows in this project — a hallucinated or out-of-evidence citation is rejected, never shown",
    source="EVAL.md §10.3",
    severity="BLOCKER",
    tags=["phase:P5"],
)
async def ev_p5_04():
    evidence = [
        {"doc_id": "real-1", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z", "text": "crashes a lot"},
        {"doc_id": "real-2", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z", "text": "battery drain"},
    ]

    # A citation ref outside the retrieved evidence's range (only 1-2
    # are valid here) must be rejected, even alongside a valid one.
    raised = False
    try:
        grounding.validate_response({"type": "answer", "text": "See doc.", "citations": [1, 99]}, evidence)
    except grounding.GroundingViolation:
        raised = True
    assert raised, "a citation ref outside the retrieved evidence set must never validate"

    # A response citing only real, in-range refs must pass, mapped back
    # to the real doc_ids.
    ok = grounding.validate_response({"type": "answer", "text": "See doc.", "citations": [1, 2]}, evidence)
    assert set(ok.citations) == {"real-1", "real-2"}

    # End to end: a real chat turn where the scripted provider hallucinates
    # a citation must degrade to a decline, never surface the hallucinated
    # answer to the user.
    with tempfile.TemporaryDirectory(prefix="ev-p504-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p504")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            async with sq.ops_db(project_dir) as ops_conn:
                await seed_and_index(committer, ops_conn, [
                    doc_row("seeded-1", config.id, "The app crashes every time I open the camera."),
                ])
                reader = await dk.get_reader(project_dir)
                provider = fake.groq_like(script=[{
                    "type": "answer",
                    "text": "Users report crashes, see ref 42.",
                    "citations": [42],  # only ref 1 exists for this single-document evidence set
                }])
                async with sq.app_db(Path(tmp) / "app.sqlite") as app_conn:
                    result = await ask(ops_conn, app_conn, reader, [provider], config.id, "What crashes are reported?")

            assert result["type"] == "insufficient_evidence", "an out-of-range citation ref must degrade the turn, never surface as-is"
        finally:
            await dk.forget_committer(project_dir)
