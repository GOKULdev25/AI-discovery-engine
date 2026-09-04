"""App Store reviews — 🟢 Green (A§2.1). `itunes.apple.com` RSS
`customerreviews` JSON feed, no key needed. Hard cap: 500 reviews per
country (10 pages x 50) — `expand()` over the project's configured
locales is the only way to widen coverage (A§16.3 decision 3).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.pipeline.ids import compute_doc_id, hash_author

EXTRACTOR_VERSION = "appstore-1"
MAX_PAGES = 10
_ID_RE = re.compile(r"/id(\d+)")
_HOST_RE = re.compile(r"^https?://(itunes|apps)\.apple\.com/", re.IGNORECASE)


class AppStoreConnector:
    id = "appstore"
    lane = "api"

    def match(self, url: str) -> JobSpec | None:
        if not _HOST_RE.match(url):
            return None
        m = _ID_RE.search(url)
        if not m:
            return None
        return JobSpec(url=url, params={"app_id": m.group(1)})

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        locales = ctx.config.locales or ["us"]
        return [
            JobSpec(url=job.url, params={**job.params, "country": country})
            for country in locales
        ]

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        app_id = job.params["app_id"]
        country = job.params.get("country", "us")

        start_page = 1
        if job.params.get("_resume_after"):
            start_page = int(job.params["_resume_after"]) + 1

        last_seen_ids: set[str] = set()
        for page in range(start_page, MAX_PAGES + 1):
            url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews/"
                f"page={page}/id={app_id}/sortby=mostrecent/json"
            )
            resp = await ctx.fetch(url)
            try:
                data = resp.json()
            except ValueError as exc:
                raise ExtractionError(FailureCode.PARSE_ERROR, f"malformed JSON: {exc}") from exc

            entries = data.get("feed", {}).get("entry", [])
            if isinstance(entries, dict):  # a single-entry feed comes back as an object, not a list
                entries = [entries]

            reviews = [e for e in entries if "author" in e and "content" in e]
            page_ids = {e.get("id", {}).get("label", "") for e in reviews}
            if not reviews or page_ids <= last_seen_ids:
                # Apple repeats the last real page past the end rather than
                # erroring — page_ids <= last_seen_ids catches that repeat.
                await ctx.checkpoint(str(page - 1))
                return
            last_seen_ids = page_ids

            for entry in reviews:
                author_name = entry.get("author", {}).get("name", {}).get("label")
                author_hash = hash_author(author_name)
                text = entry.get("content", {}).get("label", "")
                rating_label = entry.get("im:rating", {}).get("label")
                source_url = f"https://itunes.apple.com/{country}/review?id={app_id}"
                doc_id = compute_doc_id("appstore", source_url, author_hash, text)
                authored_at = None
                updated_label = entry.get("updated", {}).get("label")
                if updated_label:
                    try:
                        authored_at = datetime.fromisoformat(updated_label).astimezone(timezone.utc).isoformat()
                    except ValueError:
                        authored_at = None

                yield Doc(
                    doc_id=doc_id,
                    source="appstore",
                    doc_type="review",
                    source_url=source_url,
                    subject=entry.get("title", {}).get("label"),
                    product_id=app_id,
                    variant=country,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    authored_at=authored_at,
                    author_hash=author_hash,
                    text=text,
                    rating=float(rating_label) if rating_label is not None else None,
                    engagement={
                        "vote_sum": entry.get("im:voteSum", {}).get("label"),
                        "vote_count": entry.get("im:voteCount", {}).get("label"),
                        "app_version": entry.get("im:version", {}).get("label"),
                    },
                    lane=self.lane,
                    extractor_version=EXTRACTOR_VERSION,
                    raw=entry,
                )

            await ctx.checkpoint(str(page))
