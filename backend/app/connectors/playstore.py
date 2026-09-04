"""Play Store reviews — 🟢 Green (A§2.1). `google-play-scraper` wraps
Google's own unofficial `batchexecute` RPC. Heaviest jitter of the four
connectors (A§10.2) since this is an undocumented endpoint.

Uses `ctx.call_paced()` rather than `ctx.fetch()` — see that method's
docstring for why: this library does its own synchronous HTTP, and
reimplementing the batchexecute protocol by hand is out of scope. Rate
limiting and jitter stay structural either way.
"""

from __future__ import annotations
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from google_play_scraper import Sort, reviews
from google_play_scraper.features.reviews import _ContinuationToken

from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.pipeline.ids import compute_doc_id, hash_author

EXTRACTOR_VERSION = "playstore-1"
PAGE_SIZE = 100
MAX_PAGES = 50  # generous safety cap; the feed naturally exhausts well before this

# Country -> the language whose reviews that market actually surfaces.
# Verified live (2026-08-29, Docs/FEASIBILITY_LOG.md): `reviews()`'s
# `country` argument does NOT partition review content — `us` and `in`
# with the same `lang` returned byte-identical review IDs. `lang` is the
# real partitioning key. expand() below dedupes on *language*, not
# locale, so two configured countries that map to the same language
# don't pay for the same fetch twice.
_COUNTRY_LANG = {"us": "en", "gb": "en", "in": "hi"}


class PlayStoreConnector:
    id = "playstore"
    lane = "api"

    def match(self, url: str) -> JobSpec | None:
        parsed = urlparse(url)
        if "play.google.com" not in parsed.netloc:
            return None
        if "/apps/details" not in parsed.path:
            return None
        app_id = parse_qs(parsed.query).get("id", [None])[0]
        if not app_id:
            return None
        return JobSpec(url=url, params={"app_id": app_id})

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        locales = ctx.config.locales or ["us"]
        # One job per distinct *language* — not per configured country —
        # since country doesn't partition review content here. The first
        # country that maps to a given language lends its code as the
        # API's required `country` argument.
        seen_langs: dict[str, str] = {}
        for country in locales:
            lang = _COUNTRY_LANG.get(country, "en")
            seen_langs.setdefault(lang, country)
        return [
            JobSpec(url=job.url, params={**job.params, "country": country, "lang": lang})
            for lang, country in seen_langs.items()
        ]

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        app_id = job.params["app_id"]
        country = job.params.get("country", "us")
        lang = job.params.get("lang", "en")

        token: _ContinuationToken | None = None
        if job.params.get("_resume_after"):
            token = _ContinuationToken(
                token=job.params["_resume_after"], lang=lang, country=country,
                sort=Sort.NEWEST, count=PAGE_SIZE, filter_score_with=None, filter_device_with=None,
            )

        for _ in range(MAX_PAGES):
            try:
                page, token = await ctx.call_paced(
                    reviews, app_id, lang=lang, country=country,
                    sort=Sort.NEWEST, count=PAGE_SIZE, continuation_token=token,
                )
            except Exception as exc:  # the library raises its own exception types
                message = str(exc).lower()
                if "not found" in message or "404" in message:
                    raise ExtractionError(FailureCode.NOT_FOUND, str(exc)) from exc
                raise ExtractionError(FailureCode.NETWORK_ERROR, str(exc)) from exc

            if not page:
                return

            for entry in page:
                author_hash = hash_author(entry.get("userName"))
                text = entry.get("content") or ""
                review_id = entry.get("reviewId", "")
                source_url = f"https://play.google.com/store/apps/details?id={app_id}&reviewId={review_id}"
                doc_id = compute_doc_id("playstore", source_url, author_hash, text)

                authored_at = None
                at_value = entry.get("at")
                if isinstance(at_value, datetime):
                    authored_at = at_value.replace(tzinfo=timezone.utc).isoformat()

                yield Doc(
                    doc_id=doc_id,
                    source="playstore",
                    doc_type="review",
                    source_url=source_url,
                    product_id=app_id,
                    variant=lang,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    authored_at=authored_at,
                    author_hash=author_hash,
                    text=text,
                    rating=float(entry["score"]) if entry.get("score") is not None else None,
                    engagement={
                        "thumbs_up": entry.get("thumbsUpCount"),
                        "app_version": entry.get("appVersion"),
                    },
                    lane=self.lane,
                    extractor_version=EXTRACTOR_VERSION,
                    raw=_json_safe(entry),
                )

            cursor = token.token if token is not None else None
            await ctx.checkpoint(cursor)
            if not cursor:
                return


def _json_safe(entry: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in entry.items()}
