"""EV-P7-07, 08 — MCP is a front door, not a second implementation, and
it respects project scoping (EVAL.md §6.9, QA finding 19). Every tool in
`mcp_server.py` is a thin adapter that calls the exact REST handler
function `main.py` wires up for the same operation — verified here by
calling the tool through FastMCP's own `call_tool()` (in-process, no
stdio/subprocess) and checking the result against what the REST layer
independently reports for the same project.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.jobs.engine import forget_engine
from app.mcp_server import create_mcp_server
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from evals.harness import api_client, make_settings
from evals.registry import eval_case


def _tool_json(result) -> dict | list:
    """`FastMCP.call_tool` returns just `content_blocks` for a
    dict-returning tool (one `TextContent` of JSON), but
    `(content_blocks, structured_result)` for a list-returning one
    (`list_projects`) — and for a list, `content_blocks` is one block
    *per list item*, not one block holding the whole array, so the only
    reliable read for a list-returning tool is the structured half
    (unwrapped from its `{"result": [...]}` envelope)."""
    if isinstance(result, tuple):
        _content, structured = result
        if isinstance(structured, dict) and list(structured.keys()) == ["result"]:
            return structured["result"]
        return structured
    assert len(result) == 1
    return json.loads(result[0].text)


@eval_case(
    "EV-P7-07",
    proves="MCP is a front door, not a second implementation: every MCP tool routes through the same job engine; no logic exists in MCP that is absent from REST",
    source="A§13.1",
    severity="MAJOR",
    tags=["phase:P7"],
)
async def ev_p7_07():
    with tempfile.TemporaryDirectory(prefix="ev-p707-") as tmp:
        settings = make_settings(Path(tmp))
        mcp = create_mcp_server(settings)
        resolver = ProjectResolver(settings)

        created = _tool_json(await mcp.call_tool("create_project", {"name": "p707"}))
        project_id = created["id"]
        try:
            async with api_client(settings) as client:
                # The REST surface independently confirms the project MCP
                # just created — same directory, same warehouse, same job
                # engine, not a parallel MCP-only record of anything.
                resp = await client.get(f"/projects/{project_id}")
                assert resp.status_code == 200, "a project MCP created must be visible to the REST API — same engine underneath"
                assert resp.json()["name"] == "p707"

                extracted = _tool_json(
                    await mcp.call_tool("extract_links", {"project_id": project_id, "urls": ["fixture://run?count=2&latency_ms=0"]})
                )
                batch_id = extracted["batch_id"]

                from evals.harness import wait_for_batch_done

                await wait_for_batch_done(client, project_id, batch_id, timeout=15)

                # query_project must be the same keyset-paginated documents
                # query REST exposes — cross-checked by calling both and
                # comparing, not just trusting MCP's own report of itself.
                mcp_docs = _tool_json(await mcp.call_tool("query_project", {"project_id": project_id}))
                rest_docs = (await client.get(f"/projects/{project_id}/documents")).json()
                assert {d["doc_id"] for d in mcp_docs["documents"]} == {d["doc_id"] for d in rest_docs["documents"]}
                assert len(mcp_docs["documents"]) == 2

                exported = _tool_json(await mcp.call_tool("export_project", {"project_id": project_id}))
                assert Path(exported["path"]).is_file(), "export_project must produce the same real .xlsx build_export writes for REST"

                projects_list = _tool_json(await mcp.call_tool("list_projects", {}))
                assert any(p["id"] == project_id for p in projects_list)
        finally:
            await forget_engine(project_id)
            await dk.forget_committer(resolver.project_dir(project_id))


@eval_case(
    "EV-P7-08",
    proves="MCP respects project scoping: an MCP client scoped to project A cannot read, export, or query project B",
    source="EVAL.md §6.9",
    severity="BLOCKER",
    tags=["phase:P7"],
)
async def ev_p7_08():
    with tempfile.TemporaryDirectory(prefix="ev-p708-") as tmp:
        settings = make_settings(Path(tmp))
        mcp = create_mcp_server(settings)
        resolver = ProjectResolver(settings)

        project_a = _tool_json(await mcp.call_tool("create_project", {"name": "p708-a"}))["id"]
        project_b = _tool_json(await mcp.call_tool("create_project", {"name": "p708-b"}))["id"]
        try:
            batch_a = _tool_json(
                await mcp.call_tool("extract_links", {"project_id": project_a, "urls": ["fixture://run?count=1&latency_ms=0&link=a"]})
            )["batch_id"]
            batch_b = _tool_json(
                await mcp.call_tool("extract_links", {"project_id": project_b, "urls": ["fixture://run?count=1&latency_ms=0&link=b"]})
            )["batch_id"]

            async with api_client(settings) as client:
                from evals.harness import wait_for_batch_done

                await wait_for_batch_done(client, project_a, batch_a, timeout=15)
                await wait_for_batch_done(client, project_b, batch_b, timeout=15)

            # Interleaved calls for A then B then A again — a resolver
            # argument threaded incorrectly (QA finding 19) would show up
            # as one project's tool call returning the other's rows once
            # state from a prior call leaked forward. Nothing here is
            # cached or reused across calls: every tool re-resolves
            # `project_id` from scratch.
            docs_a1 = _tool_json(await mcp.call_tool("query_project", {"project_id": project_a}))["documents"]
            docs_b = _tool_json(await mcp.call_tool("query_project", {"project_id": project_b}))["documents"]
            docs_a2 = _tool_json(await mcp.call_tool("query_project", {"project_id": project_a}))["documents"]

            assert docs_a1 and docs_b and docs_a2
            ids_a = {d["doc_id"] for d in docs_a1}
            ids_b = {d["doc_id"] for d in docs_b}
            assert ids_a == {d["doc_id"] for d in docs_a2}, "project A's own results must not change just because B was queried in between"
            assert ids_a.isdisjoint(ids_b), "project A's query must never return project B's documents, or vice versa"

            export_a = _tool_json(await mcp.call_tool("export_project", {"project_id": project_a}))
            export_b = _tool_json(await mcp.call_tool("export_project", {"project_id": project_b}))
            assert project_a in export_a["path"] and project_b not in export_a["path"]
            assert project_b in export_b["path"] and project_a not in export_b["path"]

            # A project_id that doesn't exist must fail explicitly, never
            # silently fall back to whichever project a prior call touched.
            try:
                await mcp.call_tool("query_project", {"project_id": "does-not-exist"})
                raised = False
            except Exception:
                raised = True
            assert raised, "querying a nonexistent project_id must raise, never silently return another project's rows"
        finally:
            await forget_engine(project_a)
            await forget_engine(project_b)
            await dk.forget_committer(resolver.project_dir(project_a))
            await dk.forget_committer(resolver.project_dir(project_b))
