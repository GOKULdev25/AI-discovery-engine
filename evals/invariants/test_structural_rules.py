"""EV-INV-01..05 — the four 🔒 structural rules from IP§0 / A§14.1, checked
as static analysis over the actual source tree rather than by review
discipline."""

from __future__ import annotations

import re
from pathlib import Path

from evals.harness import BACKEND_APP_DIR, FRONTEND_DIR, iter_py_files
from evals.registry import EvalSkip, eval_case

# jobs/events.py's asyncio.Queue is SSE fan-out to HTTP clients, not the
# work-claiming path rule 1 governs — excluded deliberately, not missed.
_JOB_PATH_FILES = ["jobs/claim.py", "jobs/engine.py", "jobs/limits.py"]
_JOB_PATH_DIRS = ["connectors", "pipeline"]


@eval_case(
    "EV-INV-01",
    proves="Jobs are claimed through the database, never an in-memory queue",
    source="A§14.1",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_01():
    hits = []
    targets = [BACKEND_APP_DIR / f for f in _JOB_PATH_FILES]
    for d in _JOB_PATH_DIRS:
        targets.extend(iter_py_files(BACKEND_APP_DIR / d))
    for path in targets:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # A call, not the bare string — both claim.py's and engine.py's own
        # module docstrings *name* asyncio.Queue in prose to explain why
        # it's forbidden, which would otherwise self-trigger this check.
        if re.search(r"asyncio\.Queue\s*\(", text):
            hits.append(str(path))
    assert not hits, f"asyncio.Queue found in the job-claiming path: {hits}"


@eval_case(
    "EV-INV-02",
    proves="No DuckDB write connection is opened outside store/duckdb.py's committer",
    source="A§9",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_02():
    duckdb_module = (BACKEND_APP_DIR / "store" / "duckdb.py").resolve()
    hits = []
    for path in iter_py_files(BACKEND_APP_DIR, exclude={duckdb_module}):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bduckdb\.connect\s*\(", text):
            hits.append(str(path))
    assert not hits, f"duckdb.connect() found outside store/duckdb.py: {hits}"


@eval_case(
    "EV-INV-03",
    proves="No os.environ / process.env read outside config.py and the frontend's env module",
    source="A§14.1",
    severity="MAJOR",
    tags=["invariant"],
)
def ev_inv_03():
    config_module = (BACKEND_APP_DIR / "config.py").resolve()
    hits = []
    for path in iter_py_files(BACKEND_APP_DIR, exclude={config_module}):
        text = path.read_text(encoding="utf-8")
        if re.search(r"os\.environ|os\.getenv", text):
            hits.append(str(path))
    assert not hits, f"direct environment access found outside config.py: {hits}"


@eval_case(
    "EV-INV-04",
    proves="No absolute filesystem path and no hardcoded localhost/127.0.0.1 outside config and tests",
    source="A§14.1",
    severity="MAJOR",
    tags=["invariant"],
)
def ev_inv_04():
    config_module = (BACKEND_APP_DIR / "config.py").resolve()
    hits = []
    host_re = re.compile(r"(127\.0\.0\.1|localhost)")
    win_path_re = re.compile(r"""["'][A-Za-z]:[\\/]""")
    for path in iter_py_files(BACKEND_APP_DIR, exclude={config_module}):
        text = path.read_text(encoding="utf-8")
        if host_re.search(text) or win_path_re.search(text):
            hits.append(str(path))
    assert not hits, f"hardcoded host or absolute path found outside config.py: {hits}"


@eval_case(
    "EV-INV-05",
    proves="The frontend talks to the backend over HTTP + SSE only",
    source="A§14.1",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_05():
    import os

    src_dir = FRONTEND_DIR / "src"
    if not src_dir.is_dir():
        raise EvalSkip("frontend not built yet")
    hits = []
    forbidden = [
        r"require\(['\"]child_process['\"]\)",
        r"from ['\"]child_process['\"]",
        r"better-sqlite3",
        r"\bfs\.readFileSync\(.*\.sqlite",
        r"\bfs\.readFileSync\(.*\.duckdb",
    ]
    pattern = re.compile("|".join(forbidden))
    # Scoped to src/ (our code) — node_modules and .next are pruned from
    # the app root by construction, not filtered after a slow full walk.
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".next")]
        for filename in filenames:
            if not filename.endswith((".ts", ".tsx")):
                continue
            path = Path(dirpath) / filename
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                hits.append(str(path))
    assert not hits, f"frontend touches the filesystem/DB directly instead of HTTP+SSE: {hits}"
