"""EV-P0-01, 02, 15 — project scaffolding and deletion (A§7.1)."""

from __future__ import annotations

from evals.harness import api_client, temp_project
from evals.registry import eval_case

_EXPECTED_TREE = {
    "project.yaml", "ops.sqlite", "warehouse.duckdb", "browser-profile",
    "gate", "exports", "logs",
}


@eval_case(
    "EV-P0-01",
    proves="POST /projects produces exactly the A§7.1 tree — no missing entries, no extras",
    source="A§7.1",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_01():
    async with temp_project("p0-01") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        entries = {p.name for p in project_dir.iterdir()}
        assert entries == _EXPECTED_TREE, f"tree mismatch: got {entries}, want {_EXPECTED_TREE}"
        assert (resolver.gate_dir(project_id) / "prototypes.yaml").exists()


@eval_case(
    "EV-P0-02",
    proves="The policy default is safe: new project.yaml has session_mode: logged_out",
    source="A§5.3",
    severity="BLOCKER",
    tags=["phase:P0"],
)
async def ev_p0_02():
    async with temp_project("p0-02") as (settings, resolver, project_id):
        from app.projects import scaffold

        config = scaffold.load_project_config(resolver, project_id)
        assert config.session_mode == "logged_out"


@eval_case(
    "EV-P0-15",
    proves="Deleting a project deletes only that project — no orphaned rows anywhere",
    source="IP§0.2",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_15():
    async with temp_project("p0-15-victim") as (settings, resolver, victim_id):
        # Both projects must resolve under the SAME projects_root for this to
        # be a meaningful "only that project" check — a second temp_project
        # would get its own isolated root and prove nothing.
        from app.projects import scaffold

        survivor = await scaffold.create_project(settings, resolver, "p0-15-survivor")
        async with api_client(settings) as client:
            resp = await client.delete(f"/projects/{victim_id}")
            assert resp.status_code == 204

        assert not resolver.project_dir(victim_id).exists(), "victim project directory still exists"
        assert resolver.project_dir(survivor.id).exists(), "survivor project was affected by victim's deletion"

        async with api_client(settings) as client:
            resp = await client.get("/projects")
            ids = {p["id"] for p in resp.json()}
            assert victim_id not in ids
            assert survivor.id in ids

        await scaffold.delete_project(settings, resolver, survivor.id)
