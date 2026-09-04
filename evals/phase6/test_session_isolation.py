"""EV-P6-08, 09 — two projects never share a browser session, and
`operator_session` is unreachable without an explicit, already-running
Chrome to attach to — never silently satisfied by anything else."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.browser import session as browser_session
from app.jobs.failures import ExtractionError, FailureCode
from app.projects import scaffold
from app.projects.config import ProjectConfig
from app.projects.resolver import ProjectResolver
from evals.harness import make_settings
from evals.registry import eval_case


@eval_case(
    "EV-P6-08",
    proves="Two projects have independent browser profiles; a session in one is invisible to the other",
    source="A§7.2",
    severity="BLOCKER",
    tags=["phase:P6"],
)
async def ev_p6_08():
    with tempfile.TemporaryDirectory(prefix="ev-p608-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config_a = await scaffold.create_project(settings, resolver, "p608a")
        config_b = await scaffold.create_project(settings, resolver, "p608b")
        dir_a, dir_b = resolver.project_dir(config_a.id), resolver.project_dir(config_b.id)
        try:
            context_a = await browser_session.get_context(dir_a, session_mode="logged_out", headless=True)
            context_b = await browser_session.get_context(dir_b, session_mode="logged_out", headless=True)
            assert context_a is not context_b, "two projects must never share a browser context"

            profile_a = dir_a / "browser-profile"
            profile_b = dir_b / "browser-profile"
            assert profile_a.is_dir() and profile_b.is_dir()
            assert profile_a != profile_b

            # A cookie set in project A's context must never appear in B's.
            await context_a.add_cookies([
                {"name": "session_a_marker", "value": "secret-a", "url": "https://example.com"}
            ])
            cookies_a = await context_a.cookies()
            cookies_b = await context_b.cookies()
            assert any(c["name"] == "session_a_marker" for c in cookies_a)
            assert not any(c["name"] == "session_a_marker" for c in cookies_b), (
                "a cookie set in project A's browser context leaked into project B's"
            )
        finally:
            await browser_session.close_all()


@eval_case(
    "EV-P6-09",
    proves="session_mode: operator_session is unreachable without an explicit per-project setting and a Chrome already running to attach to",
    source="A§5.3",
    severity="BLOCKER",
    tags=["phase:P6"],
)
async def ev_p6_09():
    assert ProjectConfig(id="x", name="x", created_at="now").session_mode == "logged_out", (
        "the default must be logged_out — operator_session is never inherited by accident"
    )

    with tempfile.TemporaryDirectory(prefix="ev-p609-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p609")
        project_dir = resolver.project_dir(config.id)
        try:
            # logged_out must never attempt a CDP connection at all — if it
            # did, this would fail the same way operator_session does below
            # (nothing is listening on 9222 in this test environment).
            context = await browser_session.get_context(project_dir, session_mode="logged_out", headless=True)
            assert context is not None

            # operator_session, with no Chrome actually listening on
            # --remote-debugging-port=9222, must fail explicitly and
            # safely — never silently fall back to a normal profile
            # (which would defeat the whole point of the policy boundary).
            other_dir = resolver.project_dir((await scaffold.create_project(settings, resolver, "p609-op")).id)
            raised = False
            try:
                await browser_session.get_context(
                    other_dir, session_mode="operator_session", headless=True, cdp_url=settings.operator_cdp_url
                )
            except ExtractionError as exc:
                raised = True
                assert exc.code == FailureCode.AUTH_REQUIRED
            assert raised, "operator_session with no Chrome to attach to must raise, never silently substitute a normal profile"
        finally:
            await browser_session.close_all()
