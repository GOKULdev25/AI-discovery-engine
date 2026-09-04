"""EV-P6-10 — the firm line as a static scan: no paid proxy rotation, no
stealth/fingerprint-patching plugin, no captcha-solving dependency
anywhere. A§16 already declined all four; this is the schedule-pressure
guard that keeps a future "just this once" from creeping back in."""

from __future__ import annotations

import os
import re

from evals.harness import REPO_ROOT
from evals.registry import eval_case

_BLOCKED_TERMS = [
    "playwright-stealth", "puppeteer-extra-plugin-stealth", "undetected-chromedriver",
    "scraperapi", "brightdata", "oxylabs", "smartproxy", "zenrows", "proxymesh",
    "2captcha", "anticaptcha", "capsolver", "deathbycaptcha", "captcha-solver",
    "fingerprint-suite", "fingerprintjs-pro", "residential-proxy",
]


@eval_case(
    "EV-P6-10",
    proves="Static scan: no proxy rotation, stealth plugin, fingerprint patch, or captcha-solving dependency anywhere",
    source="A§5.4",
    severity="BLOCKER",
    tags=["phase:P6"],
)
def ev_p6_10():
    skip_dirs = {"node_modules", ".git", ".venv", ".next", "__pycache__"}
    hits = []
    manifest_names = {"pyproject.toml", "package.json"}
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            if filename not in manifest_names:
                continue
            path = os.path.join(dirpath, filename)
            try:
                text = open(path, encoding="utf-8").read().lower()
            except (UnicodeDecodeError, PermissionError):
                continue
            for term in _BLOCKED_TERMS:
                if term in text:
                    hits.append(f"{path}: {term}")

    # And the actual browser-lane source: no launch with a proxy server,
    # no stealth-plugin import/call. Matches actual code usage, not the
    # word "stealth" in prose — this codebase's own docstrings legitimately
    # explain *why* no stealth plugin is used, which must not self-flag.
    browser_dir = REPO_ROOT / "backend" / "app" / "browser"
    code_pattern = re.compile(
        r"^\s*(import|from)\s+\S*stealth\S*|StealthPlugin|stealth_sync|stealth_async|proxy\s*=\s*[\"'{]",
        re.IGNORECASE | re.MULTILINE,
    )
    for path in browser_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if code_pattern.search(text):
            hits.append(f"{path}: matches a stealth-plugin import/call or a launch-time proxy argument")

    assert not hits, f"a declined technique (A§16) was found: {hits}"
