"""EV-P4-09 — `GET /documents` paging is stable under concurrent writes.
Keyset pagination (on `(captured_at, doc_id)`) must never duplicate or
skip a row that existed when paging started, and new rows committed
mid-page must not retroactively appear in an already-fetched page or a
later page that logically precedes them."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from evals.harness import api_client, make_settings
from evals.registry import eval_case


def _row(doc_id: str, project_id: str, captured_at: str) -> dict:
    return {
        "doc_id": doc_id, "project_id": project_id, "batch_id": "b", "source": "fixture",
        "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": captured_at,
        "lane": "api", "extractor_version": "v", "raw": {}, "text": f"review {doc_id}",
    }


@eval_case(
    "EV-P4-09",
    proves="Paging GET /documents during an active batch drops and duplicates nothing",
    source="EVAL.md §6.6",
    severity="MAJOR",
    tags=["phase:P4"],
)
async def ev_p4_09():
    with tempfile.TemporaryDirectory(prefix="ev-p409-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p409")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            # 10 documents, strictly increasing captured_at, minute-spaced
            # so DESC ordering is unambiguous.
            original_ids = [f"orig-{i:02d}" for i in range(10)]
            await committer.commit_rows([
                _row(doc_id, config.id, f"2026-08-29T00:{i:02d}:00Z") for i, doc_id in enumerate(original_ids)
            ])

            async with api_client(settings) as client:
                resp = await client.get(f"/projects/{config.id}/documents", params={"limit": 5})
                page1 = resp.json()
                page1_ids = [d["doc_id"] for d in page1["documents"]]
                cursor = page1["next_cursor"]
                assert cursor is not None

                # Simulate a concurrent batch finishing mid-pagination:
                # these have LATER captured_at than everything already
                # seeded, so under DESC ordering they belong strictly
                # before the cursor position (page 1's territory) — they
                # must never leak into page 2.
                new_ids = [f"new-{i:02d}" for i in range(5)]
                await committer.commit_rows([
                    _row(doc_id, config.id, f"2026-08-29T01:{i:02d}:00Z") for i, doc_id in enumerate(new_ids)
                ])

                resp = await client.get(f"/projects/{config.id}/documents", params={"limit": 5, "cursor": cursor})
                page2 = resp.json()
                page2_ids = [d["doc_id"] for d in page2["documents"]]

            assert set(page1_ids) & set(page2_ids) == set(), "page 1 and page 2 must never overlap"
            assert not (set(page2_ids) & set(new_ids)), "documents committed after page 1 was fetched must not appear in page 2"
            assert set(page1_ids) | set(page2_ids) == set(original_ids), (
                f"the 10 original documents must be exactly covered by pages 1+2, got {sorted(page1_ids + page2_ids)}"
            )
        finally:
            await dk.forget_committer(project_dir)
