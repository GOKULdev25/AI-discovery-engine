"""EV-P6-06 — a PerimeterX (or any other) block records BLOCKED_ANTIBOT
and halts: exactly one attempt, no retry storm, no escalation. Replayed
via a recorded block-page response (`context.route()`), never a live
Myntra request."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.browser import session as browser_session
from app.jobs.engine import forget_engine
from app.jobs.failures import FailureCode, is_retryable
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.registry import eval_case

_BLOCK_PAGE_HTML = """
<html><body>
<h1>Access to this page has been denied</h1>
<p>Please verify you are a human to continue.</p>
<div id="px-captcha"></div>
</body></html>
"""


@eval_case(
    "EV-P6-06",
    proves="Resistance stops collection: a block records BLOCKED_ANTIBOT and halts — exactly one attempt, no retry storm, no escalation",
    source="A§5.4",
    severity="BLOCKER",
    tags=["phase:P6"],
)
async def ev_p6_06():
    assert not is_retryable(FailureCode.BLOCKED_ANTIBOT), (
        "BLOCKED_ANTIBOT must never be automatically retried — a site actively resisting is a signal to stop, not a puzzle to solve"
    )

    with tempfile.TemporaryDirectory(prefix="ev-p606-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p606")
        project_dir = resolver.project_dir(config.id)
        try:
            context = await browser_session.get_context(project_dir, session_mode="logged_out", headless=True)

            attempt_count = 0

            async def handler(route):
                nonlocal attempt_count
                attempt_count += 1
                await route.fulfill(body=_BLOCK_PAGE_HTML, content_type="text/html")

            await context.route("**myntra.com/**", handler)  # no leading "/" — matches "www.myntra.com" too, not just a bare-domain prefix

            from app.jobs.engine import submit_batch

            product_url = "https://www.myntra.com/tshirts/some-brand/some-product/12345678/buy"
            batch_id, links = await submit_batch(settings, config.id, [product_url])
            assert links[0]["status"] == "pending"

            import asyncio
            import time

            async with sq.ops_db(project_dir) as ops_conn:
                deadline = time.monotonic() + 20
                link_row = None
                while time.monotonic() < deadline:
                    cur = await ops_conn.execute("SELECT status, failure_code, retryable FROM links WHERE batch_id = ?", (batch_id,))
                    link_row = await cur.fetchone()
                    if link_row["status"] == "failed":
                        break
                    await asyncio.sleep(0.2)

            assert link_row is not None and link_row["status"] == "failed"
            assert link_row["failure_code"] == FailureCode.BLOCKED_ANTIBOT.value, (
                f"expected BLOCKED_ANTIBOT, got {link_row['failure_code']!r}"
            )
            assert not link_row["retryable"], "a BLOCKED_ANTIBOT failure must never be marked retryable"
            assert attempt_count == 1, f"expected exactly one attempt against a resisting site, saw {attempt_count}"
        finally:
            await forget_engine(config.id)
            await browser_session.close_all()
