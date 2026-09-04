"""Myntra — best-effort only (A§5.4, IP§6.3). PerimeterX runs
per-site behavioural models here; the firm line means no fingerprint
spoofing, no proxy rotation, no captcha solving to get past it (A§16,
"deliberately declined"). We attempt collection at human pace and, the
moment resistance shows, record `BLOCKED_ANTIBOT` and stop — exactly
once, never a retry storm, never an escalation attempt. That is a
documented limit of the design, not a defect (A§5.4).

Live investigation, 2026-08-30: browsing the category listing and three
product pages logged-out did not trigger a block within this session's
test budget, and no reviews section was found in the rendered text
within the same pass (Docs/FEASIBILITY_LOG.md has the full account).
Rather than ship a review-text parser built on an unverified guess at
Myntra's actual review format, this connector honestly reports
`EMPTY_RESULT` when it can't find a recognizable review section, and
`BLOCKED_ANTIBOT` the moment a resistance signal appears — never a
fabricated row either way (P§6).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser import session
from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.projects.resolver import get_resolver

EXTRACTOR_VERSION = "myntra-browser-1"
_PRODUCT_RE = re.compile(r"/(\d{6,})/buy")

# Known PerimeterX / generic-challenge markers. Checked against both the
# HTTP status and the rendered text — a real block can show up as either.
_BLOCK_MARKERS = (
    "access to this page has been denied",
    "unusual activity",
    "verify you are a human",
    "px-captcha",
    "are you a robot",
    "request blocked",
)


class MyntraConnector:
    id = "myntra"
    lane = "browser"

    def match(self, url: str) -> JobSpec | None:
        parsed = urlparse(url)
        if "myntra.com" not in parsed.netloc:
            return None
        if not _PRODUCT_RE.search(parsed.path):
            return None
        return JobSpec(url=url, params={})

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        return [job]

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        project_dir = get_resolver(ctx.settings).project_dir(ctx.project_id)
        context = await session.get_context(
            project_dir,
            session_mode=ctx.config.session_mode,
            headless=ctx.settings.browser_headless,
            cdp_url=ctx.settings.operator_cdp_url,
            lane_enabled=ctx.settings.browser_lane_enabled,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            resp = await ctx.call_paced_async(page.goto, job.url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError as exc:
            raise ExtractionError(FailureCode.NETWORK_ERROR, f"myntra: navigation timed out: {exc}") from exc
        except PlaywrightError as exc:
            # A connection/protocol-level failure (observed live,
            # 2026-08-30: ERR_HTTP2_PROTOCOL_ERROR under headless Chrome
            # specifically — real headful Chrome reached the same URL
            # cleanly) is ambiguous between "genuine resistance" and "a
            # network hiccup." BLOCKED_ANTIBOT is reserved for the
            # unambiguous signals below (explicit 403/429, a real block
            # page) — this stays retryable rather than assumed malicious.
            raise ExtractionError(FailureCode.NETWORK_ERROR, f"myntra: navigation failed: {exc}") from exc

        if resp is not None and resp.status in (403, 429):
            raise ExtractionError(FailureCode.BLOCKED_ANTIBOT, f"myntra: HTTP {resp.status} on {job.url} — stopping, no retry")

        visible_text = await page.inner_text("body")
        lower_text = visible_text.lower()
        if any(marker in lower_text for marker in _BLOCK_MARKERS):
            raise ExtractionError(FailureCode.BLOCKED_ANTIBOT, f"myntra: resistance signal detected on {job.url} — stopping, no retry")

        # No confirmed, verified review-text pattern for Myntra as of this
        # extractor version (see module docstring) — an honest empty
        # result, not a guessed parse.
        raise ExtractionError(FailureCode.EMPTY_RESULT, f"myntra: no recognized review content on {job.url}")
        yield  # pragma: no cover — makes this an async generator per the Connector protocol
