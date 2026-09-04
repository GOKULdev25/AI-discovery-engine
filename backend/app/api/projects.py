"""Project lifecycle endpoints (A§13)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import Settings
from app.api.deps import settings_dep
from app.export.excel import build_export
from app.projects import scaffold
from app.projects.config import ProjectConfig
from app.projects.resolver import ProjectNotFound, get_resolver
from app.store import duckdb as dk
from app.store import sqlite as sq

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str


class UpdateProjectRequest(BaseModel):
    session_mode: Literal["logged_out", "operator_session"] | None = None
    enabled_sources: list[str] | None = None
    locales: list[str] | None = None
    rate_overrides: dict[str, dict] | None = None
    gate: dict | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    created_at: str
    session_mode: str
    batch_count: int
    document_count: int


@router.post("", response_model=ProjectConfig, status_code=201)
async def create_project(body: CreateProjectRequest, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    config = await scaffold.create_project(settings, resolver, body.name)
    return config


@router.get("", response_model=list[ProjectSummary])
async def list_projects(settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    summaries = []
    for project_id in resolver.list_project_ids():
        config = scaffold.load_project_config(resolver, project_id)
        project_dir = resolver.project_dir(project_id)

        async with sq.ops_db(project_dir) as ops_conn:
            cur = await ops_conn.execute("SELECT COUNT(*) c FROM batches")
            batch_count = (await cur.fetchone())["c"]

        reader = await dk.get_reader(project_dir)
        doc_count = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

        summaries.append(ProjectSummary(
            id=config.id, name=config.name, created_at=config.created_at,
            session_mode=config.session_mode, batch_count=batch_count, document_count=doc_count,
        ))
    return summaries


@router.get("/{project_id}", response_model=ProjectConfig)
async def get_project(project_id: str, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    try:
        return scaffold.load_project_config(resolver, project_id)
    except (ProjectNotFound, FileNotFoundError):
        raise HTTPException(404, "project not found")


@router.patch("/{project_id}", response_model=ProjectConfig)
async def update_project(project_id: str, body: UpdateProjectRequest, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    try:
        config = scaffold.load_project_config(resolver, project_id)
    except (ProjectNotFound, FileNotFoundError):
        raise HTTPException(404, "project not found")

    updates = body.model_dump(exclude_unset=True)
    updated = config.model_copy(update=updates)
    scaffold.save_project_config(resolver, updated)
    return updated


@router.get("/{project_id}/export.xlsx")
async def export_project(
    project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)
):
    resolver = get_resolver(settings)
    try:
        config = scaffold.load_project_config(resolver, project_id)
    except (ProjectNotFound, FileNotFoundError):
        raise HTTPException(404, "project not found")
    out_path = await build_export(resolver, config, batch_id=batch_id)
    filename = f"{config.name}-export.xlsx".replace("/", "-")
    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    try:
        await scaffold.delete_project(settings, resolver, project_id)
    except ProjectNotFound:
        raise HTTPException(404, "project not found")
