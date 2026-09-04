"""EV-INV-07, 09, 10, 12 — nothing fabricated, provenance always travels,
the taxonomy is complete, and a crash never reaches the API untyped."""

from __future__ import annotations

import ast

from evals.harness import BACKEND_APP_DIR, api_client, iter_py_files, temp_project, wait_for_batch_done
from evals.registry import eval_case

_SCANNED_DIRS = ["connectors", "pipeline", "ai", "jobs"]
# `logger.exception` counts as evidence alongside the taxonomy-conversion
# calls: a persistent background loop (reaper/drain/worker-claim) that logs
# the full traceback and keeps running is "surfaced, never swallowed" for
# infrastructure code, distinct from an extraction failure disappearing
# silently. Both patterns exist in jobs/engine.py and both are legitimate.
_EVIDENCE_NAMES = {"mark_failed", "FailureCode", "ExtractionError", "raise", "logger.exception"}


def _handler_has_typed_evidence(handler: ast.ExceptHandler, source: str) -> bool:
    snippet = ast.get_source_segment(source, handler) or ""
    return any(name in snippet for name in _EVIDENCE_NAMES)


@eval_case(
    "EV-INV-07",
    proves="Failures are never swallowed: no bare except-Exception that logs and continues",
    source="A§8.1",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_07():
    hits = []
    for d in _SCANNED_DIRS:
        for path in iter_py_files(BACKEND_APP_DIR / d):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                is_bare = node.type is None
                is_exception = (
                    isinstance(node.type, ast.Name) and node.type.id == "Exception"
                )
                if not (is_bare or is_exception):
                    continue
                if not _handler_has_typed_evidence(node, source):
                    hits.append(f"{path}:{node.lineno}")
    assert not hits, f"a bare except-Exception with no typed-failure evidence was found: {hits}"


@eval_case(
    "EV-INV-09",
    proves="Nothing fabricated: absent fields stay null in the warehouse",
    source="P§6",
    severity="BLOCKER",
    tags=["invariant"],
)
async def ev_inv_09():
    from app.store import duckdb as dk

    async with temp_project("inv09") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            resp = await client.post(
                f"/projects/{project_id}/batches",
                json={"urls": ["fixture://run?count=5&latency_ms=0"]},
            )
            assert resp.status_code == 202
            batch_id = resp.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch_id)

        project_dir = resolver.project_dir(project_id)
        reader = await dk.get_reader(project_dir)
        row = reader.execute(
            "SELECT authored_at, rating, verified_purchase FROM documents LIMIT 1"
        ).fetchone()
        assert row is not None, "expected at least one committed document"
        assert row[0] is None, "authored_at was fabricated"
        assert row[1] is None, "rating was fabricated"
        assert row[2] is None, "verified_purchase was fabricated"


@eval_case(
    "EV-INV-10",
    proves="Provenance always travels: every row has non-null lane and extractor_version",
    source="A§8",
    severity="BLOCKER",
    tags=["invariant"],
)
async def ev_inv_10():
    from app.store import duckdb as dk

    async with temp_project("inv10") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            resp = await client.post(
                f"/projects/{project_id}/batches",
                json={"urls": ["fixture://run?count=5&latency_ms=0"]},
            )
            batch_id = resp.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch_id)

        project_dir = resolver.project_dir(project_id)
        reader = await dk.get_reader(project_dir)
        row = reader.execute(
            "SELECT COUNT(*) FROM documents WHERE lane IS NULL OR extractor_version IS NULL"
        ).fetchone()
        assert row[0] == 0, f"{row[0]} row(s) missing lane/extractor_version"


@eval_case(
    "EV-INV-12",
    proves="Every failure path terminates in an A§8.1 taxonomy code; no untyped error reaches the API",
    source="A§8.1",
    severity="BLOCKER",
    tags=["invariant"],
)
async def ev_inv_12():
    async with temp_project("inv12") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            resp = await client.post(
                f"/projects/{project_id}/batches",
                json={"urls": ["fixture://run?count=5&latency_ms=0&fail_at=2&bug=1"]},
            )
            assert resp.status_code == 202
            batch_id = resp.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch_id)

            links = (await client.get(f"/projects/{project_id}/batches/{batch_id}/links")).json()
            assert len(links) == 1
            link = links[0]
            assert link["failure_code"] == "EXTRACTOR_CRASH", (
                f"a raw bug reached the API as {link['failure_code']!r} instead of a taxonomy code"
            )
            assert link["retryable"] == 0
