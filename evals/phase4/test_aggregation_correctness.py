"""EV-P4-01, 02 — the project is the unit of aggregation by default, and
every chart's numbers are independently reproducible in raw SQL against
the same warehouse. A chart that silently disagrees with the warehouse is
worse than no chart (QA finding 17)."""

from __future__ import annotations

from pathlib import Path

from app.store import duckdb as dk
from evals.harness import api_client, make_settings, wait_for_batch_done
from evals.registry import eval_case


@eval_case(
    "EV-P4-01",
    proves="Charts aggregate the whole project by default; a batch filter narrows them",
    source="A§7.2",
    severity="MAJOR",
    tags=["phase:P4"],
)
async def ev_p4_01():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ev-p401-") as tmp:
        settings = make_settings(Path(tmp))
        async with api_client(settings) as client:
            resp = await client.post("/projects", json={"name": "p401"})
            project_id = resp.json()["id"]

            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": ["fixture://run?count=5&latency_ms=0&link=a"]})
            batch_a = resp.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch_a)

            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": ["fixture://run?count=7&latency_ms=0&link=b"]})
            batch_b = resp.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch_b)

            resp = await client.get(f"/projects/{project_id}/analytics/sources")
            assert resp.json()["meta"]["document_count"] == 12, "project-wide default should sum both batches"

            resp = await client.get(f"/projects/{project_id}/analytics/sources", params={"batch_id": batch_a})
            assert resp.json()["meta"]["document_count"] == 5, "a batch filter must narrow to just that batch"

            resp = await client.get(f"/projects/{project_id}/analytics/sources", params={"batch_id": batch_b})
            assert resp.json()["meta"]["document_count"] == 7


@eval_case(
    "EV-P4-02",
    proves="Every chart's numbers are recomputed independently in SQL and match exactly — silent aggregation drift is indistinguishable from a real finding",
    source="EVAL.md §6.6",
    severity="BLOCKER",
    tags=["phase:P4"],
)
async def ev_p4_02():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ev-p402-") as tmp:
        settings = make_settings(Path(tmp))
        async with api_client(settings) as client:
            resp = await client.post("/projects", json={"name": "p402"})
            project_id = resp.json()["id"]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": ["fixture://run?count=17&latency_ms=0"]})
            await wait_for_batch_done(client, project_id, resp.json()["batch_id"])

            api_resp = await client.get(f"/projects/{project_id}/analytics/sources")
            api_data = {row["source"]: row["doc_count"] for row in api_resp.json()["data"]}
            api_total = api_resp.json()["meta"]["document_count"]

        from app.projects.resolver import ProjectResolver

        resolver = ProjectResolver(settings)
        reader = await dk.get_reader(resolver.project_dir(project_id))
        independent = dict(
            reader.execute(
                "SELECT source, COUNT(*) FROM documents WHERE project_id = ? GROUP BY source", [project_id]
            ).fetchall()
        )
        independent_total = reader.execute(
            "SELECT COUNT(*) FROM documents WHERE project_id = ?", [project_id]
        ).fetchone()[0]

        assert api_data == independent, f"API source breakdown {api_data} != independently-computed {independent}"
        assert api_total == independent_total == 17
