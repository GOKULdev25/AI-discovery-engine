"""Creates the A§7.1 project tree exactly — no missing entries, no extras
(EV-P0-01). A project is a directory: zip it, move it, `rm -rf` it, and
nothing outside is affected.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

import yaml

from app.config import Settings
from app.projects.config import ProjectConfig
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq

_STARTER_PROTOTYPES = """\
# gate/prototypes.yaml — research-question-specific prototype sentences
# (A§7.2, A§11.2). The embedding-similarity gate stage scores each document
# against these. Replace with sentences specific to this project's research
# question; ship 2-3 to start and refine from what lands in "ambiguous".
#
# Write these as concrete example sentences a real document might contain,
# not abstract descriptions of a category — bge-small's cosine similarity
# barely separates "This review describes a specific problem the user
# experienced" from "This text is spam", since both are equally
# meta-descriptions about text; two clusters of real example phrasings
# separate cleanly (EV-P2-06).

keep:
  - "The app keeps crashing every time I open it, this really needs to be fixed."
  - "I love this app, it works great and has saved me so much time."
  - "The battery drains way too fast since the last update, very disappointing."
drop:
  - "Buy cheap watches now at this link, limited time offer, click here!"
  - "This post has been removed by a moderator for violating community rules."
  - "Subscribe to my channel for more content like this, link in bio."
"""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


def generate_project_id(name: str) -> str:
    slug = _slugify(name)[:40]
    suffix = secrets.token_hex(3)  # 6 hex chars
    return f"{slug}-{suffix}"


async def create_project(settings: Settings, resolver: ProjectResolver, name: str) -> ProjectConfig:
    project_id = generate_project_id(name)
    project_dir = resolver.project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=False)

    config = ProjectConfig(
        id=project_id,
        name=name,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    resolver.project_yaml_path(project_id).write_text(
        yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8"
    )

    # ops.sqlite — open applies migrations, then close; scaffold owns no
    # long-lived connection.
    ops_conn = await sq.open_ops_db(project_dir)
    await ops_conn.close()

    # warehouse.duckdb — apply migrations and close; the committer opens
    # its own long-lived connection lazily, on first real use.
    await dk.ensure_migrated(project_dir)

    resolver.browser_profile_dir(project_id).mkdir(parents=True, exist_ok=True)

    gate_dir = resolver.gate_dir(project_id)
    gate_dir.mkdir(parents=True, exist_ok=True)
    resolver.gate_prototypes_path(project_id).write_text(_STARTER_PROTOTYPES, encoding="utf-8")

    resolver.exports_dir(project_id).mkdir(parents=True, exist_ok=True)
    resolver.logs_dir(project_id).mkdir(parents=True, exist_ok=True)

    return config


async def delete_project(settings: Settings, resolver: ProjectResolver, project_id: str) -> None:
    import shutil

    from app.jobs.engine import forget_engine

    project_dir = resolver.require_exists(project_id)
    await forget_engine(project_id)  # stops workers/reaper/drain and awaits their connections closing
    await dk.forget_committer(project_dir)
    shutil.rmtree(project_dir)


def load_project_config(resolver: ProjectResolver, project_id: str) -> ProjectConfig:
    path = resolver.project_yaml_path(project_id)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ProjectConfig.model_validate(data)


def save_project_config(resolver: ProjectResolver, config: ProjectConfig) -> None:
    path = resolver.project_yaml_path(config.id)
    path.write_text(yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8")
