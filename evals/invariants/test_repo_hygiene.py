"""EV-INV-06, 08, 11, 13, 14 — repo-hygiene invariants."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from evals.harness import BACKEND_APP_DIR, BACKEND_DIR, REPO_ROOT, iter_py_files
from evals.registry import eval_case


@eval_case(
    "EV-INV-06",
    proves="No module builds a project path by string concatenation outside the resolver",
    source="IP§0.2",
    severity="MAJOR",
    tags=["invariant"],
)
def ev_inv_06():
    resolver_module = (BACKEND_APP_DIR / "projects" / "resolver.py").resolve()
    hits = []
    for path in iter_py_files(BACKEND_APP_DIR, exclude={resolver_module}):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.projects_root\b", text):
            hits.append(str(path))
    assert not hits, f".projects_root accessed outside the resolver: {hits}"


@eval_case(
    "EV-INV-08",
    proves="Politeness is structural: no connector imports or calls httpx directly",
    source="A§10.1",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_08():
    base_module = (BACKEND_APP_DIR / "connectors" / "base.py").resolve()
    hits = []
    for path in iter_py_files(BACKEND_APP_DIR / "connectors", exclude={base_module}):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bimport httpx\b|\bhttpx\.", text):
            hits.append(str(path))
    assert not hits, f"a connector references httpx directly instead of ctx.fetch(): {hits}"


_BLOCKED_PACKAGES = [
    "scraperapi", "brightdata", "oxylabs", "smartproxy", "zenrows",
    "scrapingbee", "2captcha", "anticaptcha", "capsolver", "deathbycaptcha",
    "openai", "cohere", "anthropic", "replicate",
]


@eval_case(
    "EV-INV-11",
    proves="The $0 constraint: no paid proxy, captcha, scraping-API, or non-Gemini/Groq/Ollama hosted-inference dependency",
    source="A§1",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_11():
    import os

    hits = []
    # node_modules must be pruned from the walk itself (not filtered after)
    # — pnpm's tree has a package.json per package, and `rglob` would
    # enumerate all of them before any filter runs, which is what made
    # this eval pathologically slow once the frontend existed. We only
    # care about our own declared dependencies anyway, never a
    # transitive dependency's own manifest.
    skip_dirs = {"node_modules", ".git", ".venv", ".next", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            path = Path(dirpath) / filename
            if filename == "pyproject.toml":
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                deps = data.get("project", {}).get("dependencies", [])
                for extra in data.get("project", {}).get("optional-dependencies", {}).values():
                    deps = deps + extra
                for dep in deps:
                    name = re.split(r"[<>=\[; ]", dep, maxsplit=1)[0].lower()
                    if name in _BLOCKED_PACKAGES:
                        hits.append(f"{path}: {dep}")
            elif filename == "package.json":
                text = path.read_text(encoding="utf-8").lower()
                for pkg in _BLOCKED_PACKAGES:
                    if f'"{pkg}"' in text:
                        hits.append(f"{path}: {pkg}")
    assert not hits, f"a paid/forbidden dependency was found: {hits}"


_SECRET_PATTERNS = [
    re.compile(r"AIzaSy[0-9A-Za-z_-]{35}"),          # Google API key
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),               # Groq key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                 # generic secret-key shape
]


@eval_case(
    "EV-INV-13",
    proves="No API key, token, or cookie in logs, exports, reports, fixtures, or committed files",
    source="A§8.1",
    severity="BLOCKER",
    tags=["invariant"],
)
def ev_inv_13():
    import os

    hits = []
    # node_modules (pnpm's store is thousands of hardlinked files) must be
    # pruned from the walk itself, not just filtered after — `rglob` would
    # still enumerate every entry inside it first, which is what made this
    # eval pathologically slow once the frontend existed.
    skip_dirs = {".git", "node_modules", ".venv", ".next", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.name == ".env" or path.suffix in {".sqlite", ".duckdb", ".wal"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                continue
            for pattern in _SECRET_PATTERNS:
                if pattern.search(text):
                    hits.append(str(path))
                    break
    assert not hits, f"a real-looking secret was found in a committed/generated file: {hits}"


_ALLOWED_HOSTS_IN_EVALS = {"eval", "127.0.0.1", "localhost"}


@eval_case(
    "EV-INV-14",
    proves="An automatic (non-live) eval run makes zero external network calls",
    source="EVAL.md §3.4",
    severity="MAJOR",
    tags=["invariant"],
)
def ev_inv_14():
    evals_dir = REPO_ROOT / "evals"
    hits = []
    # example.{com,org,net} is the IANA-reserved documentation domain
    # (RFC 2606) — used in evals as a deliberately-unsupported test URL,
    # never actually fetched.
    real_host_re = re.compile(
        r"https?://(?!eval\b|127\.0\.0\.1|localhost|example\.(com|org|net)\b)"
        r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    )
    # A real-looking host string is only a live-network risk if the file
    # doesn't also demonstrably intercept the transport that would carry
    # it — the golden-corpus fixtures (real API URL shapes, used purely
    # as match()/classify() test data or routed through one of these)
    # would otherwise false-positive on every connector eval.
    mocked_transport_re = re.compile(
        r"MockTransport|ASGITransport|mock\.patch\.object\(httpx\.AsyncClient"
        r"|mock\.patch\.object\(playstore_mod|mock\.patch\.object\(reddit_mod|FakeReddit"
        # `forget_engine` right after enqueueing is this codebase's other
        # offline idiom: stop the worker pool before it can claim and
        # actually fetch a real-looking URL that was inserted purely to
        # inspect classification/enqueue state (test_retry_correctness.py).
        r"|forget_engine"
        # Phase 6's recorded-session idiom: a real Playwright browser
        # navigates to a real-looking URL, but `context.route()`/
        # `page.route()` intercepts it before any request leaves the
        # machine, replaying a captured page instead.
        r"|\.route\("
    )
    for path in evals_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "tags=" in text and re.search(r'tags\s*=\s*\[[^\]]*["\']live["\']', text):
            continue  # live-tagged evals are permitted to touch real hosts
        if mocked_transport_re.search(text):
            continue  # network is demonstrably intercepted in this file
        if real_host_re.search(text):
            hits.append(str(path))
    assert not hits, f"a non-'live' eval references a real external host: {hits}"
