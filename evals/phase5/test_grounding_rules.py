"""EV-P5-01, 02, 03, 07 — the four P§8/A§12 answer-shape rules: answer
with citations when evidence supports it, decline when it doesn't,
clarify without also answering, and the denominator is always documents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.ai.providers import fake
from app.chat import grounding
from app.chat.retrieval import hybrid_retrieve
from app.chat.service import ask
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.phase5._helpers import doc_row, seed_and_index
from evals.registry import eval_case


@eval_case(
    "EV-P5-01",
    proves='"What do people complain about most?" is answered from retrieved evidence with doc_id citations',
    source="P§8",
    severity="BLOCKER",
    tags=["phase:P5"],
)
async def ev_p5_01():
    with tempfile.TemporaryDirectory(prefix="ev-p501-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p501")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            async with sq.ops_db(project_dir) as ops_conn:
                await seed_and_index(committer, ops_conn, [
                    doc_row("d1", config.id, "The app crashes constantly, worst bug I've seen, please fix the crashing."),
                    doc_row("d2", config.id, "Battery drains so fast since the update, terrible battery life."),
                ])
                reader = await dk.get_reader(project_dir)
                evidence = await hybrid_retrieve(ops_conn, reader, "What do people complain about most?")
                assert evidence, "retrieval must find the seeded complaint documents"
                cited = evidence[0]["doc_id"]

                provider = fake.groq_like(script=[{
                    "type": "answer",
                    "text": f"The most common complaints are app crashes and battery drain, based on {len(evidence)} documents.",
                    "citations": [1],  # ref 1 == evidence[0], i.e. `cited`
                }])
                async with sq.app_db(Path(tmp) / "app.sqlite") as app_conn:
                    result = await ask(ops_conn, app_conn, reader, [provider], config.id, "What do people complain about most?")

            assert result["type"] == "answer"
            assert result["citations"], "an answer must carry at least one citation"
            assert cited in result["citations"]
        finally:
            await dk.forget_committer(project_dir)


@eval_case(
    "EV-P5-02",
    proves='A question with no supporting evidence gets an explicit "I don\'t have enough data", not a guess',
    source="P§8",
    severity="BLOCKER",
    tags=["phase:P5"],
)
async def ev_p5_02():
    with tempfile.TemporaryDirectory(prefix="ev-p502-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p502")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)  # never seeded with any documents
            reader = await dk.get_reader(project_dir)
            async with sq.ops_db(project_dir) as ops_conn, sq.app_db(Path(tmp) / "app.sqlite") as app_conn:
                # An empty provider script — if the code tried to call a
                # provider at all for zero-evidence questions, this would
                # raise ProviderQuotaExhausted instead of declining cleanly.
                provider = fake.groq_like(script=[])
                result = await ask(ops_conn, app_conn, reader, [provider], config.id, "What do people say about the checkout flow?")

            assert result["type"] == "insufficient_evidence"
            assert result["citations"] == []
            assert provider.calls == [], "no evidence should mean no provider call at all, not a wasted one"
        finally:
            await dk.forget_committer(project_dir)


@eval_case(
    "EV-P5-03",
    proves="An ambiguous question returns needs_clarification and no answer — never both in the same turn",
    source="A§12",
    severity="BLOCKER",
    tags=["phase:P5"],
)
async def ev_p5_03():
    evidence = [{"doc_id": "d1", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z", "text": "fine"}]

    clarify = grounding.validate_response(
        {"type": "needs_clarification", "text": "Which app version or time period do you mean?", "citations": []},
        evidence,
    )
    assert clarify.type == "needs_clarification"
    assert clarify.citations == []

    # The actual hard rule is about answer *content*, not incidental
    # metadata: a model attaching citations to a genuine clarifying
    # question (real behavior, found live) isn't "answering and asking
    # at once" — but the user must still never see a citation on
    # anything that isn't type "answer", so it's stripped, not trusted.
    stray_citation = grounding.validate_response(
        {"type": "needs_clarification", "text": "Do you mean version 2?", "citations": ["d1"]}, evidence
    )
    assert stray_citation.type == "needs_clarification"
    assert stray_citation.citations == [], "a non-answer's citations must be dropped, never surfaced to the user"


@eval_case(
    "EV-P5-07",
    proves='No answer says "% of users" or "N people" — the denominator is documents throughout',
    source="A§12",
    severity="BLOCKER",
    tags=["phase:P5"],
)
async def ev_p5_07():
    evidence = [{"doc_id": "d1", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z", "text": "fine"}]

    for bad_text in [
        "About 40% of users mentioned battery issues.",
        "12 people complained about the checkout flow.",
        "Most of the users were happy with the update.",
    ]:
        raised = False
        try:
            grounding.validate_response({"type": "answer", "text": bad_text, "citations": [1]}, evidence)
        except grounding.GroundingViolation:
            raised = True
        assert raised, f"expected a people-denominator violation for: {bad_text!r}"

    # The documents-framing equivalent must be accepted.
    ok = grounding.validate_response(
        {"type": "answer", "text": "About 40% of documents mentioned battery issues.", "citations": [1]}, evidence
    )
    assert ok.type == "answer"
