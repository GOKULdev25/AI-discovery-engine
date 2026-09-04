"""FastAPI + SSE entrypoint (A§13). The frontend talks to this over
HTTP + SSE only — no shared filesystem, no Python imports (IP rule 4 🔒,
EV-INV-05)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    analytics,
    batches,
    chat,
    documents,
    gate_config,
    projects,
    quota,
    sources,
)
from app.browser import session as browser_session
from app.api.deps import settings_dep
from app.config import Settings, get_settings
from app.http_client import new_http_client, shared_ssl_context
from app.jobs.engine import resume_active_projects, stop_all_engines
from app.pipeline.enrich_local import warmup as warmup_enrichment_models
from app.projects.resolver import ProjectNotFound
from app.store import duckdb as dk


def create_app(settings: Settings | None = None, warmup_models: bool = True) -> FastAPI:
    """`settings` is normally left unset (loaded from `.env`/environment).
    The eval harness passes an explicit `Settings` pointed at a throwaway
    directory, so both the request-time dependency and the startup
    resume-scan use the same isolated project root — never the real one.

    `warmup_models=False` skips loading the fastembed ONNX model at
    startup — the eval harness passes this, since that load can trigger a
    one-time network fetch of the model file, which an automatic
    (non-`live`) eval run must never do (EV-INV-14)."""
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Building the first SSL context, and the first httpx.AsyncClient
        # (which lazily imports httpcore/anyio internals), together cost
        # ~600ms on this platform (see app/http_client.py) — pay it once
        # here, at boot, instead of on whichever request happens to be
        # first (EV-P0-14's <200ms bar). The fastembed model load costs
        # ~10s the same way (app/pipeline/enrich_local.py).
        shared_ssl_context()
        async with new_http_client():
            pass
        # warmup() is itself a no-op for the ONNX model when
        # Settings.embeddings_enabled is False (a 512MB host), so a
        # constrained deployment never pays the ~10s or the ~300MB.
        if warmup_models:
            await warmup_enrichment_models()
        await resume_active_projects(resolved_settings)
        yield
        await stop_all_engines()
        await dk.close_all()
        await browser_session.close_all()

    app = FastAPI(title="AI Discovery Engine", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings is not None:
        app.dependency_overrides[settings_dep] = lambda: settings

    @app.exception_handler(ProjectNotFound)
    async def _project_not_found_handler(request: Request, exc: ProjectNotFound):
        # `resolver.require_exists()` raises this from any handler that
        # calls it directly (batches.py, and every Phase 4 endpoint) —
        # one place to turn it into the 404 every caller actually wants,
        # instead of each handler remembering its own try/except (found
        # live, 2026-08-29: GET /batches/{id} on an unknown project
        # returned a raw 500, not a 404).
        return JSONResponse(status_code=404, content={"detail": "project not found"})

    app.include_router(projects.router)
    app.include_router(batches.router)
    app.include_router(quota.router)
    app.include_router(documents.router)
    app.include_router(analytics.router)
    app.include_router(chat.router)
    app.include_router(sources.router)
    app.include_router(gate_config.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
