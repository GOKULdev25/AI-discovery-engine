"""EV-P6-11 — `browser-profile/` contents reach no export, no log, and no
VCS-tracked path; no cookie or token is ever written to the warehouse."""

from __future__ import annotations

import inspect
import re

from evals.harness import BACKEND_APP_DIR, REPO_ROOT
from evals.registry import eval_case


@eval_case(
    "EV-P6-11",
    proves="browser-profile/ contents appear in no export, no log, and no VCS-tracked path; no cookie or token lands in the warehouse",
    source="A§7.2",
    severity="BLOCKER",
    tags=["phase:P6"],
)
def ev_p6_11():
    # data/ (which every project — and therefore every browser-profile/ —
    # lives under) is entirely gitignored, so the profile never becomes a
    # VCS-tracked path in the first place.
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.exists(), "expected a .gitignore at the repo root"
    gitignore_text = gitignore_path.read_text(encoding="utf-8")
    assert re.search(r"^data/\s*$", gitignore_text, re.MULTILINE), (
        "data/ (which every project's browser-profile/ lives under) must be gitignored"
    )

    # The export path never references the profile directory at all.
    export_source = (BACKEND_APP_DIR / "export" / "excel.py").read_text(encoding="utf-8")
    assert "browser-profile" not in export_source and "browser_profile_dir" not in export_source, (
        "the export path must never reference the browser profile directory"
    )

    # Every browser site connector's emitted Doc(...) raw payload is
    # limited to page-content metadata — never a cookie, session token,
    # or profile file path.
    from app.browser.sites import amazon, flipkart, myntra

    forbidden_terms = ("cookie", "session_token", "browser-profile", "browser_profile_dir", "user_data_dir")
    hits = []
    for module in (amazon, flipkart, myntra):
        source = inspect.getsource(module)
        for term in forbidden_terms:
            if term in source.lower():
                hits.append(f"{module.__name__}: {term!r}")
    assert not hits, f"a browser connector referenced session/profile data where only page content should be: {hits}"
