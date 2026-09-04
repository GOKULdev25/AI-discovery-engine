"""Amazon — 🟡 amber, best-effort (A§2.3, IP§6.3). Live-verified,
2026-08-30: `/product-reviews/<ASIN>/` shows a sign-in wall to a
logged-out session (the plan's May-2026 finding still holds, just with
a sign-in prompt rather than literally "Page Not Found" — the practical
effect is identical: reviews are unreachable there). The only reviews a
`logged_out` session can ever reach are the featured ones embedded on
the product page itself — measured live at 7 for a real product, inside
the plan's stated 8-13 range (Docs/DECISIONS.md A§16.2).

This is not an anti-bot problem and no amount of browser realism solves
it (A§2.3) — the data is genuinely absent from the logged-out DOM, so
this connector does not attempt the gated `/product-reviews/` page at
all. `operator_session` (A§5.3) would see more, by design — the
gate is what changes, not this extractor.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser import session
from app.browser.text_extract import parse_amazon_reviews_from_text
from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.pipeline.ids import compute_doc_id, hash_author
from app.projects.resolver import get_resolver

EXTRACTOR_VERSION = "amazon-browser-1"
_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _parse_authored_at(authored_text: str | None) -> str | None:
    """"15 August 2026" -> an ISO timestamp. Amazon's date-stamp is
    day-precise (unlike Flipkart's month/year-only), so promoting it to
    `authored_at` isn't fabricating precision that was never there."""
    if not authored_text:
        return None
    try:
        dt = datetime.strptime(authored_text.strip(), "%d %B %Y").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


class AmazonConnector:
    id = "amazon"
    lane = "browser"

    def match(self, url: str) -> JobSpec | None:
        parsed = urlparse(url)
        if "amazon." not in parsed.netloc:
            return None
        m = _ASIN_RE.search(unquote(parsed.path))
        if not m:
            return None
        return JobSpec(url=url, params={"asin": m.group(1), "netloc": parsed.netloc})

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

        product_url = f"https://{job.params['netloc']}/dp/{job.params['asin']}"
        try:
            resp = await ctx.call_paced_async(page.goto, product_url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError as exc:
            raise ExtractionError(FailureCode.NETWORK_ERROR, f"amazon: navigation timed out: {exc}") from exc
        except PlaywrightError as exc:
            raise ExtractionError(FailureCode.NETWORK_ERROR, f"amazon: navigation failed: {exc}") from exc

        if resp is not None and resp.status in (403, 429):
            raise ExtractionError(FailureCode.BLOCKED_ANTIBOT, f"amazon: HTTP {resp.status} on {product_url}")
        if resp is not None and resp.status == 404:
            raise ExtractionError(FailureCode.NOT_FOUND, f"amazon: {product_url} returned 404")

        # The featured-reviews section is mid-page; scroll to trigger any
        # lazy-loaded content the same way a human browsing would. This is
        # local mouse movement, not a request to the remote site, so it
        # doesn't go through the paced limiter — that governs navigation,
        # not every local action in between.
        for _ in range(4):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(0.4)

        visible_text = await page.inner_text("body")
        lines = [ln.strip() for ln in visible_text.split("\n") if ln.strip()]
        reviews = parse_amazon_reviews_from_text(lines)

        if not reviews:
            raise ExtractionError(
                FailureCode.EMPTY_RESULT, f"amazon: no featured reviews found on {product_url} (logged_out ceiling)"
            )

        for review in reviews:
            author_hash = hash_author(review["author"])
            text = review["text"]
            doc_id = compute_doc_id(self.id, product_url, author_hash, text)
            engagement = {"helpful": review["helpful_count"]} if review["helpful_count"] is not None else None
            yield Doc(
                doc_id=doc_id,
                source=self.id,
                doc_type="review",
                source_url=product_url,
                captured_at=datetime.now(timezone.utc).isoformat(),
                authored_at=_parse_authored_at(review["authored_text"]),
                author_hash=author_hash,
                text=text,
                rating=review["rating"],
                verified_purchase=review["verified_purchase"],
                engagement=engagement,
                lane=self.lane,
                extractor_version=EXTRACTOR_VERSION,
                raw={"variant": review["variant"], "logged_out_ceiling": True},
            )
