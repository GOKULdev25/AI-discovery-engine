"""EV-P1-01 — the P§8 criterion 1 acceptance test: mixed links across all
four green connectors in, normalized rows out, zero manual cleanup.
Runs against cassette-equivalent canned responses (EVAL.md §3.4) — no
live network, fully deterministic. Real connector behavior (App Store,
Play Store) was additionally verified live during development; see
`Docs/FEASIBILITY_LOG.md`, 2026-08-29.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest import mock

import httpx

import app.connectors.playstore as playstore_mod
import app.connectors.reddit as reddit_mod
from app.jobs.engine import submit_batch
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.corpora.golden import fake_reddit, mock_data
from evals.harness import make_settings, wait_for_batch_done_direct
from evals.registry import eval_case


def _fake_get_factory():
    async def fake_get(self, url, params=None, **kwargs):
        if "itunes.apple.com" in url:
            page = int(re.search(r"page=(\d+)", url).group(1))
            data = mock_data.APPSTORE_PAGE_1 if page == 1 else mock_data.APPSTORE_PAGE_EMPTY
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
        if "googleapis.com/youtube" in url:
            page_token = (params or {}).get("pageToken")
            data = {"items": []} if page_token else mock_data.YOUTUBE_PAGE_1
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
        raise AssertionError(f"unexpected live URL in an offline eval: {url}")

    return fake_get


def _fake_reviews(app_id, lang="en", country="us", sort=None, count=100, continuation_token=None, **kw):
    if continuation_token is not None:
        return [], None
    return list(mock_data.PLAYSTORE_PAGE_1), None


@eval_case(
    "EV-P1-01",
    proves="20-ish mixed links across all four green connectors -> normalized rows, zero manual cleanup (P§8 criterion 1)",
    source="P§8",
    severity="BLOCKER",
    tags=["phase:P1"],
)
async def ev_p1_01():
    with tempfile.TemporaryDirectory(prefix="ev-golden-") as tmp:
        settings = make_settings(
            Path(tmp), youtube_api_key="fake-key-for-offline-eval",
            reddit_client_id="fake-id", reddit_client_secret="fake-secret",
        )
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "golden")
        project_dir = resolver.project_dir(config.id)

        urls = [
            "https://apps.apple.com/us/app/testapp/id123456789",
            "https://play.google.com/store/apps/details?id=com.test.app",
            "https://www.youtube.com/watch?v=abc123",
            "https://www.reddit.com/r/test/comments/post1/a_discussion_thread/",
            "not a valid url",
            # A binary asset, not a page — Lane 3 (P7) declines this shape
            # the same way any other connector declines a URL it doesn't
            # handle, so this stays genuinely UNSUPPORTED_SOURCE even with
            # the "paste any link" fallback registered (EV-P7-05).
            "https://example.com/totally-unsupported-file.pdf",
        ]

        fake_submission = fake_reddit.make_fake_submission()
        try:
            with mock.patch.object(httpx.AsyncClient, "get", _fake_get_factory()), \
                 mock.patch.object(playstore_mod, "reviews", _fake_reviews), \
                 mock.patch.object(
                     reddit_mod.asyncpraw, "Reddit",
                     lambda *a, **kw: fake_reddit.FakeReddit(submission=fake_submission),
                 ):
                batch_id, links = await submit_batch(settings, config.id, urls)
                assert len(links) == len(urls)

                async with sq.ops_db(project_dir) as ops_conn:
                    final = await wait_for_batch_done_direct(ops_conn, batch_id, timeout=15)

            assert final["counts"].get("done") == 4, f"expected 4 successful links, got {final['counts']}"
            assert final["counts"].get("failed") == 2, f"expected 2 typed failures, got {final['counts']}"

            async with sq.ops_db(project_dir) as ops_conn:
                cur = await ops_conn.execute(
                    "SELECT url, status, failure_code, connector_id FROM links ORDER BY created_at"
                )
                rows = {r["url"]: dict(r) for r in await cur.fetchall()}

            assert rows["not a valid url"]["failure_code"] == "INVALID_URL"
            assert rows["https://example.com/totally-unsupported-file.pdf"]["failure_code"] == "UNSUPPORTED_SOURCE"
            for url, connector_id in [
                (urls[0], "appstore"), (urls[1], "playstore"), (urls[2], "youtube"), (urls[3], "reddit"),
            ]:
                assert rows[url]["status"] == "done", f"{connector_id} link did not complete: {rows[url]}"
                assert rows[url]["connector_id"] == connector_id

            reader = await dk.get_reader(project_dir)
            by_source = dict(reader.execute("SELECT source, COUNT(*) FROM documents GROUP BY source").fetchall())
            assert by_source.get("appstore", 0) > 0
            assert by_source.get("playstore", 0) > 0
            assert by_source.get("youtube", 0) > 0
            assert by_source.get("reddit", 0) > 0

            total = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            raw_null = reader.execute("SELECT COUNT(*) FROM documents WHERE raw IS NULL").fetchone()[0]
            lane_null = reader.execute(
                "SELECT COUNT(*) FROM documents WHERE lane IS NULL OR extractor_version IS NULL"
            ).fetchone()[0]
            assert raw_null == 0, "raw must be populated on every row (the escape hatch, EV-P1-07)"
            assert lane_null == 0, "lane/extractor_version must be populated on every row"
            assert total > 0
        finally:
            from app.jobs.engine import forget_engine

            await forget_engine(config.id)
            await dk.forget_committer(project_dir)
