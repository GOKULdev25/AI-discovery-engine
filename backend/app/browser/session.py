"""Real Chrome, real persistent profile (A§5.1, A§5.2, IP§6.1). A real
Chrome binary with a real profile on a residential connection has
nothing to spoof, because nothing is fake — a categorically different
posture from stealth plugins, and why this lane works without a single
paid proxy (A§5.4).

One context per project, cached for the process lifetime. The profile
directory lives *inside* the project (A§7.1, A§7.2), so one project
signed into Amazon can never contaminate another running `logged_out`,
and a block incurred in one project stays there.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import BrowserContext, Playwright, async_playwright

from app.jobs.failures import ExtractionError, FailureCode

_playwright: Playwright | None = None
_playwright_lock = asyncio.Lock()


@dataclass
class _Owned:
    context: BrowserContext
    owned: bool  # False for operator_session (CDP-attached) — never close someone else's browser


_contexts: dict[str, _Owned] = {}
_contexts_lock = asyncio.Lock()


async def _get_playwright() -> Playwright:
    global _playwright
    async with _playwright_lock:
        if _playwright is None:
            _playwright = await async_playwright().start()
        return _playwright


async def get_context(
    project_dir: Path, *, session_mode: str = "logged_out", headless: bool = False,
    cdp_url: str | None = None, lane_enabled: bool = True,
) -> BrowserContext:
    """One persistent Playwright context per project, cached across jobs
    so a signed-in session survives between links in the same batch —
    reopening an empty profile per job would defeat "sign one, it
    sticks" (A§5.1).

    `operator_session` attaches to a Chrome the operator already started
    with `--remote-debugging-port=<cdp_url's port>` (A§5.3). `cdp_url`
    is required for that mode — every real caller passes `Settings.
    operator_cdp_url` (IP§0.1 rule 3: config.py is the only place
    allowed to bake in a host/port, so this module never hardcodes one).

    The application never sees, stores, or transmits a credential
    either way; the only difference is whose profile this is. That
    borrowed context is never closed by `close_context`/`close_all` —
    this app didn't open it and has no business tearing it down.
    """
    if not lane_enabled:
        # The one chokepoint every Lane 2 site passes through, so a host
        # with no desktop Chrome (A§14) declines once, here, rather than
        # each site file remembering to check. `UNSUPPORTED_SOURCE` is the
        # honest code: the URL is fine and the connector exists — this
        # deployment simply cannot reach it (A§8.1).
        raise ExtractionError(
            FailureCode.UNSUPPORTED_SOURCE,
            "the browser lane (Lane 2) is disabled on this deployment — it needs a real "
            "desktop Chrome with a persistent profile, which no free cloud host provides "
            "(A§14). Run this link on a local instance instead.",
        )
    key = str(project_dir)
    async with _contexts_lock:
        existing = _contexts.get(key)
        if existing is not None:
            return existing.context

        pw = await _get_playwright()
        if session_mode == "operator_session":
            try:
                browser = await pw.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise ExtractionError(
                    FailureCode.AUTH_REQUIRED,
                    f"operator_session requires Chrome already running with --remote-debugging-port "
                    f"matching {cdp_url} (A§5.1) — start it and sign in manually first",
                ) from exc
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            _contexts[key] = _Owned(context, owned=False)
        else:
            profile_dir = project_dir / "browser-profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir), channel="chrome", headless=headless
            )
            _contexts[key] = _Owned(context, owned=True)
        return context


async def close_context(project_dir: Path) -> None:
    key = str(project_dir)
    async with _contexts_lock:
        entry = _contexts.pop(key, None)
    if entry is not None and entry.owned:
        await entry.context.close()


async def close_all() -> None:
    async with _contexts_lock:
        entries = list(_contexts.values())
        _contexts.clear()
    for entry in entries:
        if entry.owned:
            await entry.context.close()
    global _playwright
    async with _playwright_lock:
        if _playwright is not None:
            await _playwright.stop()
            _playwright = None
