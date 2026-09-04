"""Reddit posts + comments — 🟢 Green (A§2.1). OAuth via `asyncpraw` is
**mandatory** — `.json` has returned 403 unauthenticated since May 2026
(A§2.3). This is sanctioned first-party API access (app credentials),
never a user login — no username/password field exists anywhere in this
file (EV-P-1-05).

Uses `ctx.call_paced_async()` rather than `ctx.fetch()`: asyncpraw does
its own async networking, but its internal rate limiting is scoped to
its own client instance, not shared across projects — routing every
asyncpraw call through this project's *global* per-source limiter is
what makes "two projects share one 100 QPM budget" (A§10.2) true.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import asyncpraw

from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode
from app.pipeline.ids import compute_doc_id, hash_author

EXTRACTOR_VERSION = "reddit-1"
MORE_COMMENTS_LIMIT = 32  # deliberate cap, not "walk every MoreComments blindly" (IP§1.2)

_HOST_RE = re.compile(r"^https?://(www\.|old\.)?(reddit\.com|redd\.it)", re.IGNORECASE)


class RedditConnector:
    id = "reddit"
    lane = "api"

    def match(self, url: str) -> JobSpec | None:
        if not _HOST_RE.match(url):
            return None
        if "/comments/" not in url and "redd.it/" not in url:
            return None  # only submission (thread) links — not subreddit listings, in Phase 1
        return JobSpec(url=url, params={})

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        return [job]

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        s = ctx.settings
        if not s or not s.reddit_client_id or not s.reddit_client_secret:
            raise ExtractionError(FailureCode.AUTH_REQUIRED, "Reddit app credentials are not configured")

        reddit = asyncpraw.Reddit(
            client_id=s.reddit_client_id,
            client_secret=s.reddit_client_secret,
            user_agent=s.reddit_user_agent,
        )
        doc_id_by_reddit_id: dict[str, str] = {}
        try:
            try:
                # `fetch=True` (the default) already awaits the network
                # fetch inside this call — an explicit `.load()` after it
                # would be a second, redundant request per thread.
                submission = await ctx.call_paced_async(reddit.submission, url=job.url)
            except Exception as exc:
                raise _classify(exc) from exc

            post_doc = _doc_from_submission(submission)
            doc_id_by_reddit_id[f"t3_{submission.id}"] = post_doc.doc_id
            yield post_doc

            try:
                await submission.comments.replace_more(limit=MORE_COMMENTS_LIMIT)
            except Exception as exc:
                raise _classify(exc) from exc

            count = 0
            for comment in submission.comments.list():
                parent_doc_id = doc_id_by_reddit_id.get(comment.parent_id)
                doc = _doc_from_comment(comment, parent_doc_id)
                doc_id_by_reddit_id[f"t1_{comment.id}"] = doc.doc_id
                yield doc
                count += 1
                if count % 50 == 0:
                    await ctx.checkpoint(str(count))  # heartbeat only — see module docstring
        finally:
            await reddit.close()


def _classify(exc: Exception) -> ExtractionError:
    status = getattr(getattr(exc, "response", None), "status", None) or getattr(exc, "status", None)
    if status == 404 or type(exc).__name__ in ("NotFound", "Redirect"):
        return ExtractionError(FailureCode.NOT_FOUND, str(exc))
    if status == 403:
        return ExtractionError(FailureCode.AUTH_REQUIRED, str(exc))
    if status == 429:
        return ExtractionError(FailureCode.RATE_LIMITED, str(exc))
    return ExtractionError(FailureCode.NETWORK_ERROR, str(exc))


def _doc_from_submission(submission) -> Doc:
    author_name = getattr(submission.author, "name", None)
    author_hash = hash_author(author_name)
    text = submission.selftext or submission.title or ""
    source_url = f"https://www.reddit.com{submission.permalink}"
    doc_id = compute_doc_id("reddit", source_url, author_hash, text)
    return Doc(
        doc_id=doc_id,
        source="reddit",
        doc_type="post",
        source_url=source_url,
        subject=submission.title,
        captured_at=datetime.now(timezone.utc).isoformat(),
        authored_at=datetime.fromtimestamp(submission.created_utc, tz=timezone.utc).isoformat(),
        author_hash=author_hash,
        text=text,
        engagement={"score": submission.score, "num_comments": submission.num_comments},
        lane="api",
        extractor_version=EXTRACTOR_VERSION,
        raw={"id": submission.id, "title": submission.title, "score": submission.score},
    )


def _doc_from_comment(comment, parent_doc_id: str | None) -> Doc:
    author_name = getattr(comment.author, "name", None)
    author_hash = hash_author(author_name)
    text = comment.body or ""
    source_url = f"https://www.reddit.com{comment.permalink}"
    doc_id = compute_doc_id("reddit", source_url, author_hash, text)
    return Doc(
        doc_id=doc_id,
        source="reddit",
        doc_type="comment",
        source_url=source_url,
        captured_at=datetime.now(timezone.utc).isoformat(),
        authored_at=datetime.fromtimestamp(comment.created_utc, tz=timezone.utc).isoformat(),
        author_hash=author_hash,
        text=text,
        parent_id=parent_doc_id,
        engagement={"score": comment.score},
        lane="api",
        extractor_version=EXTRACTOR_VERSION,
        raw={"id": comment.id, "score": comment.score},
    )
