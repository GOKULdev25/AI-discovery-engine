"""Flipkart reviews via a real, persistent Chrome profile (A§2.1 🟢,
IP§6.3). Read `text_extract.py`'s docstring for why this reads rendered
text rather than an intercepted JSON response — that was the original
plan, and live investigation (2026-08-30) found no such endpoint exists
for this page. What *is* preserved from the original design: zero CSS/
XPath selectors anywhere in this file (EV-P6-02), one tab, human-paced
navigation via the same global rate limiter every Phase 1 connector uses
(`browser` in `jobs/limits.py`, already concurrency=1 with 3-8s jitter —
no separate pacing mechanism needed here).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser import session
from app.browser.text_extract import parse_qa_from_text, parse_reviews_from_text
from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.pipeline.ids import compute_doc_id, hash_author
from app.projects.resolver import get_resolver

EXTRACTOR_VERSION = "flipkart-browser-1"
MAX_PAGES = 20  # human-paced (3-8s/page) already bounds runtime; this bounds it further (EV-P0 lesson: always cap pagination)

_PRODUCT_RE = re.compile(r"/([^/]+)/(?:p|product-reviews)/(itm[0-9a-zA-Z]+)")


class FlipkartConnector:
    id = "flipkart"
    lane = "browser"

    def match(self, url: str) -> JobSpec | None:
        parsed = urlparse(url)
        if "flipkart.com" not in parsed.netloc:
            return None
        m = _PRODUCT_RE.search(parsed.path)
        if not m:
            return None
        qs = parse_qs(parsed.query)
        pid, lid = qs.get("pid", [None])[0], qs.get("lid", [None])[0]
        if not pid or not lid:
            return None  # a product URL missing pid/lid can't reach the reviews page reliably
        return JobSpec(url=url, params={"slug": m.group(1), "itm": m.group(2), "pid": pid, "lid": lid})

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

        base_url = (
            f"https://www.flipkart.com/{job.params['slug']}/product-reviews/"
            f"{job.params['itm']}?pid={job.params['pid']}&lid={job.params['lid']}"
        )

        start_page = 1
        if job.params.get("_resume_after"):
            start_page = int(job.params["_resume_after"]) + 1

        # Q&A (A§2.1 Amber) lives on the product page, not the reviews
        # page — fetched once, only on a fresh (non-resumed) attempt, so
        # a retry that resumes review pagination from a checkpoint never
        # re-emits the same Q&A pairs. Best-effort: a failure here never
        # costs the reviews this connector exists primarily for.
        if start_page == 1:
            product_url = (
                f"https://www.flipkart.com/{job.params['slug']}/p/"
                f"{job.params['itm']}?pid={job.params['pid']}&lid={job.params['lid']}"
            )
            try:
                await ctx.call_paced_async(page.goto, product_url, wait_until="networkidle", timeout=45000)
                visible_text = await page.inner_text("body")
                qa_lines = [ln.strip() for ln in visible_text.split("\n") if ln.strip()]
                for pair in parse_qa_from_text(qa_lines):
                    question_doc_id = compute_doc_id(self.id, product_url, None, pair["question"])
                    yield Doc(
                        doc_id=question_doc_id,
                        source=self.id,
                        doc_type="qa_question",
                        source_url=product_url,
                        captured_at=datetime.now(timezone.utc).isoformat(),
                        text=pair["question"],
                        lane=self.lane,
                        extractor_version=EXTRACTOR_VERSION,
                        raw={},
                    )
                    yield Doc(
                        doc_id=compute_doc_id(self.id, product_url, None, pair["answer"]),
                        source=self.id,
                        doc_type="qa_answer",
                        source_url=product_url,
                        captured_at=datetime.now(timezone.utc).isoformat(),
                        text=pair["answer"],
                        # Every group `parse_qa_from_text` returns was
                        # bounded by a "Verified buyer" marker by
                        # construction — this isn't a guess, it's what
                        # the parse already required to emit the pair.
                        verified_purchase=True,
                        parent_id=question_doc_id,
                        lane=self.lane,
                        extractor_version=EXTRACTOR_VERSION,
                        raw={},
                    )
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                ctx.log("flipkart: Q&A fetch failed, continuing with reviews only", error=str(exc))

        last_signature: str | None = None
        page_num = start_page
        while page_num <= MAX_PAGES:
            if ctx.signal.is_set():
                return
            page_url = base_url if page_num == 1 else f"{base_url}&page={page_num}"
            try:
                resp = await ctx.call_paced_async(page.goto, page_url, wait_until="networkidle", timeout=45000)
            except PlaywrightTimeoutError as exc:
                raise ExtractionError(FailureCode.NETWORK_ERROR, f"flipkart: navigation timed out: {exc}") from exc
            except PlaywrightError as exc:
                # A connection/protocol-level failure (e.g. ERR_HTTP2_PROTOCOL_ERROR,
                # observed live 2026-08-30 specifically under headless
                # Chrome — real headful Chrome did not hit it on the same
                # URL) never even reached an HTTP response to check a
                # status code on. Retryable, not EXTRACTOR_CRASH: the
                # browser or the connection is the more likely cause than
                # a bug in this code.
                raise ExtractionError(FailureCode.NETWORK_ERROR, f"flipkart: navigation failed: {exc}") from exc

            if resp is not None and resp.status in (403, 429):
                raise ExtractionError(FailureCode.BLOCKED_ANTIBOT, f"flipkart: HTTP {resp.status} on {page_url}")
            if resp is not None and resp.status == 404:
                raise ExtractionError(FailureCode.NOT_FOUND, f"flipkart: {page_url} returned 404")

            visible_text = await page.inner_text("body")
            lines = [ln.strip() for ln in visible_text.split("\n") if ln.strip()]
            reviews = parse_reviews_from_text(lines)

            if not reviews:
                if page_num == start_page:
                    raise ExtractionError(FailureCode.EMPTY_RESULT, f"flipkart: no reviews found on {page_url}")
                return  # ran out of pages

            signature = reviews[0]["author"] + "|" + reviews[0]["text"][:40]
            if signature == last_signature:
                # `&page=N` is an unverified guess (IP§6.3 finding) — if it
                # returns the same content as the previous page, there's
                # nothing more to page through, not a reason to loop or
                # duplicate.
                return
            last_signature = signature

            for review in reviews:
                author_hash = hash_author(f"{review['author']}|{review['location'] or ''}")
                text = review["text"]
                doc_id = compute_doc_id(self.id, page_url, author_hash, text)
                engagement = {"helpful": review["helpful_count"]} if review["helpful_count"] is not None else None
                yield Doc(
                    doc_id=doc_id,
                    source=self.id,
                    doc_type="review",
                    source_url=page_url,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    authored_at=None,  # only month/year known — never promoted to a fabricated day (P§6)
                    author_hash=author_hash,
                    text=text,
                    rating=review["rating"],
                    verified_purchase=review["verified_purchase"],
                    engagement=engagement,
                    lane=self.lane,
                    extractor_version=EXTRACTOR_VERSION,
                    raw={
                        "variant": review["variant"],
                        "authored_month": review["authored_month"],
                        "location": review["location"],
                    },
                )
            await ctx.checkpoint(str(page_num))
            page_num += 1
