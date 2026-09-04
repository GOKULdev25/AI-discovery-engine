"""The ONLY place that turns a project_id into filesystem paths or open
connections (IP§0.2). Every other module asks the resolver instead of
concatenating `projects_root / project_id / ...` itself — that is what
keeps "move a project to another machine" a copy operation, and it is
exactly what EV-INV-06 greps for.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

# project_id is also a directory name — reject anything that could escape
# projects_root (path traversal, absolute paths, separators).
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class InvalidProjectId(ValueError):
    pass


class ProjectNotFound(LookupError):
    pass


class ProjectResolver:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _validate(self, project_id: str) -> str:
        if not _SAFE_ID_RE.match(project_id):
            raise InvalidProjectId(f"invalid project id: {project_id!r}")
        return project_id

    def project_dir(self, project_id: str) -> Path:
        return self._settings.projects_root / self._validate(project_id)

    def require_exists(self, project_id: str) -> Path:
        d = self.project_dir(project_id)
        if not d.is_dir():
            raise ProjectNotFound(project_id)
        return d

    def exists(self, project_id: str) -> bool:
        try:
            return self.project_dir(project_id).is_dir()
        except InvalidProjectId:
            return False

    def project_yaml_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.yaml"

    def ops_sqlite_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "ops.sqlite"

    def warehouse_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "warehouse.duckdb"

    def browser_profile_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "browser-profile"

    def gate_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "gate"

    def gate_prototypes_path(self, project_id: str) -> Path:
        return self.gate_dir(project_id) / "prototypes.yaml"

    def exports_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "exports"

    def logs_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "logs"

    def list_project_ids(self) -> list[str]:
        root = self._settings.projects_root
        if not root.is_dir():
            return []
        return sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "project.yaml").exists()
        )


_resolver: ProjectResolver | None = None


def get_resolver(settings: Settings) -> ProjectResolver:
    global _resolver
    if _resolver is None or _resolver._settings is not settings:
        _resolver = ProjectResolver(settings)
    return _resolver
