"""YouTube comments — 🟢 Green (A§2.1). Official Data API v3,
`commentThreads.list`, called directly via `ctx.fetch()` (the REST
surface is simple JSON-over-HTTPS; pulling in `google-api-python-client`
for this one call would be more dependency than the job needs).

10,000 units/day; ~1 unit per `commentThreads.list` call regardless of
`maxResults`, so paginating at 100/page is what makes the quota model in
A§11.1 (roughly 1 unit per 100 comments) hold.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.pipeline.ids import compute_doc_id, hash_author

EXTRACTOR_VERSION = "youtube-1"
API_BASE = "https://www.googleapis.com/youtube/v3/commentThreads"

# Real gap found live (2026-08-29): a single popular video can have
# millions of comments and nothing bounded the pagination loop — one link
# could burn an unbounded slice of the 10,000-unit/day quota before
# Phase 3's quota ledger exists to stop it. 100 pages x 100/page = 10,000
# comments/link, ~100 of the 10,000 daily units — consistent with App
# Store's per-country cap and Play Store's per-language cap, both of
# which exist for the same reason.
MAX_PAGES = 100

_HOST_RE = re.compile(r"^https?://(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)", re.IGNORECASE)


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/") or None
    if "/shorts/" in parsed.path:
        return parsed.path.split("/shorts/")[-1].split("/")[0] or None
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]
    return None


class YouTubeConnector:
    id = "youtube"
    lane = "api"

    def match(self, url: str) -> JobSpec | None:
        if not _HOST_RE.match(url):
            return None
        video_id = _extract_video_id(url)
        if not video_id:
            return None
        return JobSpec(url=url, params={"video_id": video_id})

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        return [job]  # one video = one job; no locale fan-out for comments

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        api_key = ctx.settings.youtube_api_key if ctx.settings else None
        if not api_key:
            raise ExtractionError(FailureCode.AUTH_REQUIRED, "YOUTUBE_API_KEY is not configured")

        video_id = job.params["video_id"]
        page_token = job.params.get("_resume_after") or None

        for _ in range(MAX_PAGES):
            params = {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": "100",
                "textFormat": "plainText",
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                resp = await ctx.fetch(API_BASE, params=params)
            except ExtractionError as exc:
                raise _reclassify(exc) from exc
            try:
                data = resp.json()
            except ValueError as exc:
                raise ExtractionError(FailureCode.PARSE_ERROR, f"malformed JSON: {exc}") from exc

            for item in data.get("items", []):
                yield from_thread_item(item, video_id, job.url)
                for reply in _replies(item):
                    yield reply

            page_token = data.get("nextPageToken")
            await ctx.checkpoint(page_token)
            if not page_token:
                return


def _reclassify(exc: ExtractionError) -> ExtractionError:
    """`ctx.fetch()` maps any 401/403 to AUTH_REQUIRED, but YouTube also
    returns 403 for quota exhaustion (retryable, resumes tomorrow) and for
    a video with comments disabled (an honest empty outcome, not an auth
    problem) — both need a different code than a real auth failure."""
    if exc.code is not FailureCode.AUTH_REQUIRED:
        return exc
    cause = exc.__cause__
    body = ""
    if cause is not None and hasattr(cause, "response"):
        body = getattr(cause.response, "text", "") or ""
    if "quotaExceeded" in body or "dailyLimitExceeded" in body:
        return ExtractionError(FailureCode.QUOTA_EXHAUSTED, str(exc))
    if "commentsDisabled" in body:
        return ExtractionError(FailureCode.EMPTY_RESULT, "comments are disabled on this video")
    return exc


def from_thread_item(item: dict, video_id: str, source_url: str) -> Doc:
    top = item.get("snippet", {}).get("topLevelComment", {})
    snippet = top.get("snippet", {})
    return _doc_from_comment_snippet(
        comment_id=top.get("id", ""), snippet=snippet, video_id=video_id,
        source_url=source_url, parent_id=None,
    )


def _replies(item: dict):
    replies = item.get("replies", {}).get("comments", [])
    video_id = item.get("snippet", {}).get("videoId", "")
    parent_id = item.get("snippet", {}).get("topLevelComment", {}).get("id")
    source_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
    for reply in replies:
        yield _doc_from_comment_snippet(
            comment_id=reply.get("id", ""), snippet=reply.get("snippet", {}),
            video_id=video_id, source_url=source_url, parent_id=parent_id,
        )


def _doc_from_comment_snippet(*, comment_id: str, snippet: dict, video_id: str, source_url: str, parent_id: str | None) -> Doc:
    author_channel = snippet.get("authorChannelId", {}).get("value") or snippet.get("authorDisplayName")
    author_hash = hash_author(author_channel)
    text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
    comment_url = f"{source_url}&lc={comment_id}" if source_url else comment_id
    doc_id = compute_doc_id("youtube", comment_url, author_hash, text)

    authored_at = None
    published_at = snippet.get("publishedAt")
    if published_at:
        try:
            authored_at = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            authored_at = None

    return Doc(
        doc_id=doc_id,
        source="youtube",
        doc_type="comment",
        source_url=comment_url,
        product_id=video_id,
        captured_at=datetime.now(timezone.utc).isoformat(),
        authored_at=authored_at,
        author_hash=author_hash,
        text=text,
        parent_id=parent_id,
        engagement={"likes": snippet.get("likeCount")},
        lane="api",
        extractor_version=EXTRACTOR_VERSION,
        raw=snippet,
    )
