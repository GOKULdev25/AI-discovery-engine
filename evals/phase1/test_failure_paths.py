"""EV-P1-11 — each connector maps a realistic failure to the right typed
code, not just its happy path (EVAL.md §6.3: "honest failure coverage").
"""

from __future__ import annotations

from unittest import mock

import httpx

from app.connectors.appstore import AppStoreConnector
from app.connectors.base import JobSpec
from app.connectors.playstore import PlayStoreConnector
from app.connectors.reddit import RedditConnector
from app.connectors.youtube import YouTubeConnector
from app.jobs.failures import ExtractionError, FailureCode
from evals.corpora.golden import fake_reddit, mock_data
from evals.harness import connector_ctx, drain
from evals.registry import eval_case


@eval_case(
    "EV-P1-11",
    proves="Connectors have honest failure coverage: a realistic failure maps to the right taxonomy code, offline",
    source="EVAL.md §6.3",
    severity="MAJOR",
    tags=["phase:P1"],
)
async def ev_p1_11():
    await _check_appstore_malformed()
    await _check_playstore_library_error()
    await _check_youtube_quota_exceeded()
    await _check_reddit_not_found()


async def _check_appstore_malformed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>", request=request)

    async with connector_ctx("appstore", transport=httpx.MockTransport(handler)) as ctx:
        connector = AppStoreConnector()
        job = JobSpec(url="https://apps.apple.com/us/app/x/id1", params={"app_id": "1", "country": "us"})
        try:
            await drain(connector.run(job, ctx))
            raise AssertionError("expected a PARSE_ERROR, got no exception")
        except ExtractionError as exc:
            assert exc.code is FailureCode.PARSE_ERROR, f"expected PARSE_ERROR, got {exc.code}"
            assert not exc.retryable


async def _check_playstore_library_error():
    import app.connectors.playstore as playstore_mod

    def raise_not_found(*args, **kwargs):
        raise Exception("App not found (404)")

    async with connector_ctx("playstore") as ctx:
        connector = PlayStoreConnector()
        job = JobSpec(url="https://play.google.com/store/apps/details?id=x", params={"app_id": "x", "country": "us", "lang": "en"})
        with mock.patch.object(playstore_mod, "reviews", raise_not_found):
            try:
                await drain(connector.run(job, ctx))
                raise AssertionError("expected NOT_FOUND, got no exception")
            except ExtractionError as exc:
                assert exc.code is FailureCode.NOT_FOUND, f"expected NOT_FOUND, got {exc.code}"


async def _check_youtube_quota_exceeded():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=mock_data.YOUTUBE_QUOTA_EXCEEDED_BODY, request=request)

    async with connector_ctx("youtube", transport=httpx.MockTransport(handler), youtube_api_key="fake") as ctx:
        connector = YouTubeConnector()
        job = JobSpec(url="https://www.youtube.com/watch?v=x", params={"video_id": "x"})
        try:
            await drain(connector.run(job, ctx))
            raise AssertionError("expected QUOTA_EXHAUSTED, got no exception")
        except ExtractionError as exc:
            assert exc.code is FailureCode.QUOTA_EXHAUSTED, f"expected QUOTA_EXHAUSTED (not a bare AUTH_REQUIRED), got {exc.code}"
            assert exc.retryable, "quota exhaustion must be retryable — it resumes tomorrow"


async def _check_reddit_not_found():
    import app.connectors.reddit as reddit_mod

    class _NotFound(Exception):
        status = 404

    async with connector_ctx("reddit", reddit_client_id="id", reddit_client_secret="secret") as ctx:
        connector = RedditConnector()
        job = JobSpec(url="https://www.reddit.com/r/test/comments/deleted/x/", params={})
        fake = fake_reddit.FakeReddit(raise_exc=_NotFound("deleted"))
        with mock.patch.object(reddit_mod.asyncpraw, "Reddit", lambda *a, **kw: fake):
            try:
                await drain(connector.run(job, ctx))
                raise AssertionError("expected NOT_FOUND, got no exception")
            except ExtractionError as exc:
                assert exc.code is FailureCode.NOT_FOUND, f"expected NOT_FOUND, got {exc.code}"
