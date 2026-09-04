"""Shared eval utilities (EVAL.md §3.4): a fresh temp project per eval, no
live network, a frozen-enough clock for anything that isn't explicitly
`live`. This module is the one place that adds `backend/` to `sys.path`,
so any eval module can `from app...` without repeating it.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
BACKEND_APP_DIR = BACKEND_DIR / "app"
FRONTEND_DIR = REPO_ROOT / "frontend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from app.config import Settings  # noqa: E402
from app.jobs import engine as job_engine  # noqa: E402
from app.projects import scaffold  # noqa: E402
from app.projects.resolver import ProjectResolver  # noqa: E402
from app.store import duckdb as dk  # noqa: E402


def iter_py_files(root: Path, exclude: set[Path] = frozenset()):
    if not root.is_dir():
        return
    for p in root.rglob("*.py"):
        if p.resolve() in exclude:
            continue
        if "__pycache__" in p.parts:
            continue
        yield p


def make_settings(data_root: Path, **overrides) -> Settings:
    # Off by default for every eval, even though `.env`'s real Gemini/Groq
    # keys load into this Settings like any other value: a ProjectEngine
    # built for an unrelated Phase 0-2 eval must never spin up the AI
    # classify loop and spend a live free-tier request (EV-INV-14). Phase 3
    # evals that actually exercise classification call its functions
    # directly with injected fake providers instead of going through this
    # background loop, so they never need to override this back on.
    overrides.setdefault("ai_classification_enabled", False)
    overrides.setdefault("browser_headless", True)
    return Settings(data_root=data_root, **overrides)


@asynccontextmanager
async def temp_project(name: str = "eval-project", **settings_overrides):
    """Yields (settings, resolver, project_id) backed by a throwaway
    directory, and tears down every process-wide singleton keyed to that
    directory on exit (committer, ops connection, engine) so evals never
    leak state into each other."""
    with tempfile.TemporaryDirectory(prefix="ev-") as tmp:
        settings = make_settings(Path(tmp), **settings_overrides)
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, name)
        project_dir = resolver.project_dir(config.id)
        try:
            yield settings, resolver, config.id
        finally:
            await job_engine.forget_engine(config.id)  # awaits worker/reaper/drain cleanup
            await dk.forget_committer(project_dir)


@asynccontextmanager
async def api_client(settings: Settings):
    """An in-process ASGI client against the real FastAPI app, with the
    settings dependency overridden to this eval's temp settings — no
    socket, no live server, fully deterministic."""
    from app.main import create_app

    app = create_app(settings=settings, warmup_models=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval") as client:
            yield client


async def wait_for_batch_done(client: httpx.AsyncClient, project_id: str, batch_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/projects/{project_id}/batches/{batch_id}")
        body = resp.json()
        if body["status"] == "done":
            return body
        await asyncio.sleep(0.05)
    raise TimeoutError(f"batch {batch_id} did not finish within {timeout}s")


@asynccontextmanager
async def connector_ctx(source: str, transport: httpx.MockTransport | None = None, **settings_overrides):
    """A `Ctx` for testing one connector's `run()`/`expand()` in isolation
    — no engine, no API, no live network. `transport` backs `ctx.fetch()`
    with a `httpx.MockTransport` (cassette-equivalent: canned responses,
    fully offline — EVAL.md §3.4) for connectors that use it directly;
    connectors using `ctx.call_paced()` (Play Store) mock the underlying
    library call instead, since it never goes through `ctx.fetch()`.
    """
    from app.connectors.base import Ctx
    from app.jobs.limits import LimiterRegistry, RateSpec
    from app.store import sqlite as sq

    with tempfile.TemporaryDirectory(prefix="ev-ctx-") as tmp:
        settings = make_settings(Path(tmp), **settings_overrides)
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, f"ctx-{source}")
        project_dir = resolver.project_dir(config.id)
        try:
            async with sq.ops_db(project_dir) as ops_conn:
                # Zero-latency limiter — these evals assert behavior, not timing.
                limiter_registry = LimiterRegistry({source: RateSpec(concurrency=8, min_interval_s=0.0)})
                http_client = httpx.AsyncClient(transport=transport) if transport else httpx.AsyncClient()
                try:
                    yield Ctx(
                        project_id=config.id, batch_id="b1", job_id="j1", link_id="l1",
                        source=source, ops_conn=ops_conn, project_config=config,
                        limiter_registry=limiter_registry, http_client=http_client,
                        settings=settings,
                    )
                finally:
                    await http_client.aclose()
        finally:
            await dk.forget_committer(project_dir)


async def drain(agen) -> list:
    return [item async for item in agen]


async def wait_for_batch_done_direct(ops_conn, batch_id: str, timeout: float = 10.0) -> dict:
    """Like `wait_for_batch_done`, for evals that drive `submit_batch()`
    directly instead of through the API (e.g. because they need to mock
    a connector's underlying library rather than an HTTP response)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cur = await ops_conn.execute("SELECT status, link_count FROM batches WHERE id = ?", (batch_id,))
        batch_row = await cur.fetchone()
        if batch_row["status"] == "done":
            cur = await ops_conn.execute(
                "SELECT status, COUNT(*) c FROM links WHERE batch_id = ? GROUP BY status", (batch_id,)
            )
            counts = {r["status"]: r["c"] for r in await cur.fetchall()}
            return {"status": "done", "counts": counts}
        await asyncio.sleep(0.05)
    raise TimeoutError(f"batch {batch_id} did not finish within {timeout}s")
