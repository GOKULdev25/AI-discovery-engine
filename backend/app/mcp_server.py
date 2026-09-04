"""The MCP front door (A§13.1). `list_projects`, `create_project`,
`extract_links`, `query_project`, `export_project` — every tool below is
a thin adapter around the exact same functions the REST API calls
(`app.api.projects`, `app.api.batches`, `app.api.documents`,
`app.export.excel`). MCP is a second front door, not a second
implementation (EV-P7-07): there is nowhere in this file that touches
the job engine, the resolver, or the warehouse directly — every real
decision is made by code the REST surface already exercises.

Each tool takes its own `project_id` explicitly and resolves settings
fresh on every call — no cached "current project," no mutable
server-instance state that could carry one call's project into the
next. That is what keeps two calls for two different projects in the
same MCP session from crossing the boundary (QA finding 19, EV-P7-08) —
the same discipline `chat/retrieval.py` already needs for the same
reason (A§7.2).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP

from app.api import batches, documents, projects
from app.api.batches import SubmitBatchRequest
from app.api.projects import CreateProjectRequest
from app.config import Settings, get_settings
from app.export.excel import build_export
from app.projects import scaffold
from app.projects.resolver import ProjectNotFound, get_resolver


async def _call(coro: Any) -> Any:
    """Every REST handler this module calls raises `HTTPException` for an
    expected failure (project not found, batch too large) — a shape that
    means nothing to a caller with no HTTP context. Re-raised as
    `ValueError` so an MCP client gets a plain, readable tool error
    instead of a FastAPI-flavored exception leaking through a protocol
    that was never HTTP to begin with."""
    try:
        return await coro
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    resolved_settings = settings or get_settings()
    mcp = FastMCP("ai-discovery-engine")

    @mcp.tool()
    async def list_projects() -> list[dict]:
        """List every project, with its batch and document counts."""
        summaries = await _call(projects.list_projects(resolved_settings))
        return [s.model_dump() for s in summaries]

    @mcp.tool()
    async def create_project(name: str) -> dict:
        """Create a new project (a fresh directory, warehouse, and gate
        config) and return its config, including the generated `id` every
        other tool call needs."""
        config = await _call(projects.create_project(CreateProjectRequest(name=name), resolved_settings))
        return config.model_dump()

    @mcp.tool()
    async def extract_links(project_id: str, urls: list[str]) -> dict:
        """Submit links to a project for extraction. Returns immediately
        with a `batch_id` and each link's initial status — workers claim
        and dispatch in the background, same as `POST /batches`."""
        result = await _call(batches.create_batch(project_id, SubmitBatchRequest(urls=urls), resolved_settings))
        return result.model_dump()

    @mcp.tool()
    async def query_project(
        project_id: str,
        batch_id: str | None = None,
        source: str | None = None,
        gate_band: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Page through a project's extracted documents, optionally
        narrowed to one batch or source — cross-batch by default, the
        same keyset-paginated query `GET /projects/{id}/documents` runs."""
        return await _call(
            documents.list_documents(
                project_id,
                batch_id=batch_id,
                source=source,
                gate_band=gate_band,
                cursor=cursor,
                limit=limit,
                settings=resolved_settings,
            )
        )

    @mcp.tool()
    async def export_project(project_id: str, batch_id: str | None = None) -> dict:
        """Build this project's Excel export (documents, links, run_info)
        and return the path to the written file."""
        resolver = get_resolver(resolved_settings)
        try:
            config = scaffold.load_project_config(resolver, project_id)
        except (ProjectNotFound, FileNotFoundError) as exc:
            raise ValueError("project not found") from exc
        out_path = await build_export(resolver, config, batch_id=batch_id)
        return {"path": str(out_path)}

    return mcp


mcp = create_mcp_server()

if __name__ == "__main__":
    mcp.run(transport="stdio")
