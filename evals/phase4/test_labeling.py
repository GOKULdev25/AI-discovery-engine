"""EV-P4-04, 05, 06 — the disclosure discipline: mixed sources are never
merged into one undifferentiated bar, the lexicon sentiment *prior* is
structurally distinct from any future LLM-derived label, and every chart
states its denominator (N documents, sources, capture window)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from evals.harness import api_client, make_settings
from evals.registry import eval_case

_NOW = "2026-08-29T00:00:00Z"


def _row(doc_id: str, project_id: str, source: str, text: str) -> dict:
    return {
        "doc_id": doc_id, "project_id": project_id, "batch_id": "b", "source": source,
        "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": _NOW,
        "lane": "api", "extractor_version": "v", "raw": {}, "text": text,
    }


@eval_case(
    "EV-P4-04",
    proves="Mixed-source data is never collapsed into one bar — each chart breaks sources out and flags mixed_source",
    source="A§12",
    severity="MAJOR",
    tags=["phase:P4"],
)
async def ev_p4_04():
    with tempfile.TemporaryDirectory(prefix="ev-p404-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p404")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            await committer.commit_rows([
                _row("d1", config.id, "playstore", "Great app, love it."),
                _row("d2", config.id, "playstore", "Terrible, crashes constantly."),
                _row("d3", config.id, "reddit", "Anyone else having battery issues with this app?"),
            ])

            async with api_client(settings) as client:
                resp = await client.get(f"/projects/{config.id}/analytics/sources")
                body = resp.json()
                assert body["meta"]["mixed_source"] is True
                sources_seen = {row["source"] for row in body["data"]}
                assert sources_seen == {"playstore", "reddit"}, "each source must appear as its own row, never merged"
                for row in body["data"]:
                    assert row["doc_count"] < 3, "no single row should silently claim the whole project's count"
        finally:
            await dk.forget_committer(project_dir)


@eval_case(
    "EV-P4-05",
    proves="The lexicon sentiment prior is structurally distinct from any LLM-derived label — no chart merges them",
    source="A§11.2",
    severity="BLOCKER",
    tags=["phase:P4"],
)
async def ev_p4_05():
    with tempfile.TemporaryDirectory(prefix="ev-p405-") as tmp:
        settings = make_settings(Path(tmp))
        async with api_client(settings) as client:
            resp = await client.post("/projects", json={"name": "p405"})
            project_id = resp.json()["id"]
            resp = await client.get(f"/projects/{project_id}/analytics/sentiment")
            body = resp.json()

            # The field name itself carries "prior" — never a bare
            # "sentiment" key that a future LLM label could be merged into
            # without anyone noticing the ambiguity.
            assert "sentiment_prior_breakdown" in body
            assert "sentiment" not in body, "a bare 'sentiment' key would be structurally ambiguous with a future LLM label"
            assert "sentiment_label" not in body and "sentiment_final" not in body


@eval_case(
    "EV-P4-06",
    proves="Every chart states its denominator: document count, sources, and capture window",
    source="IP§4",
    severity="MAJOR",
    tags=["phase:P4"],
)
async def ev_p4_06():
    with tempfile.TemporaryDirectory(prefix="ev-p406-") as tmp:
        settings = make_settings(Path(tmp))
        async with api_client(settings) as client:
            resp = await client.post("/projects", json={"name": "p406"})
            project_id = resp.json()["id"]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": ["fixture://run?count=3&latency_ms=0"]})
            from evals.harness import wait_for_batch_done

            await wait_for_batch_done(client, project_id, resp.json()["batch_id"])

            for path in ("volume", "sources", "sentiment", "ratings", "themes"):
                resp = await client.get(f"/projects/{project_id}/analytics/{path}")
                meta = resp.json()["meta"]
                for field in ("document_count", "sources", "mixed_source", "captured_from", "captured_to"):
                    assert field in meta, f"{path} response is missing denominator field {field!r}"
                assert meta["document_count"] == 3

            resp = await client.get(f"/projects/{project_id}/analytics/failures")
            assert "total_links" in resp.json(), "failures' natural denominator is links attempted, not documents"
