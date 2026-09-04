"""EV-P4-07, 03 — the empty state is explicit (never a zeroed chart that
reads as a real finding), and the dashboard stays fast at real scale."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from evals.harness import api_client, make_settings
from evals.registry import eval_case

_NOW = "2026-08-29T00:00:00Z"


@eval_case(
    "EV-P4-07",
    proves="A project with 0 documents renders an explicit empty state, never a zeroed chart that reads as a real finding",
    source="EVAL.md §6.6",
    severity="MAJOR",
    tags=["phase:P4"],
)
async def ev_p4_07():
    with tempfile.TemporaryDirectory(prefix="ev-p407-") as tmp:
        settings = make_settings(Path(tmp))
        async with api_client(settings) as client:
            resp = await client.post("/projects", json={"name": "p407"})
            project_id = resp.json()["id"]

            for path in ("volume", "sources", "ratings", "themes"):
                resp = await client.get(f"/projects/{project_id}/analytics/{path}")
                body = resp.json()
                assert body["meta"]["document_count"] == 0
                assert body["data"] == [], f"{path} must return an empty series, not a zeroed/fabricated one"

            resp = await client.get(f"/projects/{project_id}/analytics/sentiment")
            body = resp.json()
            assert body["meta"]["document_count"] == 0
            assert body["sentiment_prior_breakdown"] == []

            resp = await client.get(f"/projects/{project_id}/analytics/failures")
            assert resp.json()["total_links"] == 0
            assert resp.json()["data"] == []


@eval_case(
    "EV-P4-03",
    proves="A project with 100k documents renders the dashboard in under a second (p95)",
    source="IP§4",
    severity="MAJOR",
    tags=["phase:P4", "slow"],
)
async def ev_p4_03():
    with tempfile.TemporaryDirectory(prefix="ev-p403-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p403")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            total = 100_000
            chunk = 10_000
            sources = ["playstore", "appstore", "reddit", "youtube"]
            for start in range(0, total, chunk):
                rows = [
                    {
                        "doc_id": f"doc-{i}", "project_id": config.id, "batch_id": "b",
                        "source": sources[i % len(sources)], "doc_type": "review",
                        "source_url": f"fixture://{i}", "captured_at": _NOW,
                        "lane": "api", "extractor_version": "v", "raw": {},
                        "text": f"review number {i} about the product, quality point {i % 50}",
                        "rating": float((i % 5) + 1),
                    }
                    for i in range(start, start + chunk)
                ]
                await committer.commit_rows(rows)

            reader = await dk.get_reader(project_dir)
            count = reader.execute("SELECT COUNT(*) FROM documents WHERE project_id = ?", [config.id]).fetchone()[0]
            assert count == total

            async with api_client(settings) as client:
                for path in ("volume", "sources", "sentiment", "ratings", "themes"):
                    t0 = time.monotonic()
                    resp = await client.get(f"/projects/{config.id}/analytics/{path}")
                    elapsed = time.monotonic() - t0
                    assert resp.status_code == 200
                    assert resp.json()["meta"]["document_count"] == total
                    assert elapsed < 1.0, f"{path} took {elapsed:.2f}s against {total} documents, budget is <1s"
        finally:
            await dk.forget_committer(project_dir)
