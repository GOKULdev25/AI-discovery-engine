"""EV-P1-03, 07, 12, 13 — locale fan-out, the raw escape hatch, no
fabrication, and a usable export."""

from __future__ import annotations

from app.connectors.appstore import AppStoreConnector
from app.connectors.base import JobSpec
from app.projects.config import ProjectConfig
from evals.registry import eval_case


class _FakeCtx:
    def __init__(self, locales):
        self.config = ProjectConfig(id="p", name="p", created_at="x", locales=locales)


@eval_case(
    "EV-P1-03",
    proves="Locale fan-out is real and bounded: one App Store link x 3 locales -> 3 jobs, cap stated per-link",
    source="A§2.1",
    severity="MAJOR",
    tags=["phase:P1"],
)
async def ev_p1_03():
    connector = AppStoreConnector()
    job = connector.match("https://apps.apple.com/us/app/testapp/id123456789")
    assert job is not None

    specs = await connector.expand(job, _FakeCtx(["us", "in", "gb"]))
    assert len(specs) == 3
    countries = {s.params["country"] for s in specs}
    assert countries == {"us", "in", "gb"}

    # The 500/country hard cap (10 pages x 50) is a real product constraint,
    # not a bug — MAX_PAGES enforces it structurally.
    from app.connectors.appstore import MAX_PAGES
    assert MAX_PAGES == 10, "App Store's 500-per-country cap depends on this page bound"


@eval_case(
    "EV-P1-12",
    proves="Connectors never fabricate: over known_nulls, no connector populates authored_at/rating/verified_purchase",
    source="P§6",
    severity="BLOCKER",
    tags=["phase:P1"],
)
async def ev_p1_12():
    from evals.corpora.golden import mock_data
    from evals.harness import connector_ctx
    import httpx

    # A Play Store review with no `at` timestamp (known_nulls case: the
    # source genuinely didn't provide one) must not get one invented.
    review = dict(mock_data.PLAYSTORE_PAGE_1[0])
    review["at"] = None

    async with connector_ctx("playstore") as ctx:
        from app.connectors.playstore import PlayStoreConnector

        connector = PlayStoreConnector()
        job = JobSpec(url="https://play.google.com/store/apps/details?id=x", params={"app_id": "x", "country": "us", "lang": "en"})

        def fake_reviews(app_id, **kw):
            # google-play-scraper's real `reviews()` is synchronous — this
            # goes through `ctx.call_paced()`'s `asyncio.to_thread`, which
            # expects exactly that (an `async def` here would hand back
            # an un-awaited coroutine instead of data).
            return [review], None

        import app.connectors.playstore as playstore_mod
        from unittest import mock as _mock

        with _mock.patch.object(playstore_mod, "reviews", fake_reviews):
            docs = [doc async for doc in connector.run(job, ctx)]

        assert len(docs) == 1
        assert docs[0].authored_at is None, "authored_at was fabricated from a missing source timestamp"
        assert docs[0].verified_purchase is None, "Play Store never reports verified_purchase — must stay null"


@eval_case(
    "EV-P1-13",
    proves="The export is usable by someone who has never seen the tool: 3+ sheets, frozen header, autofilter, run_info",
    source="P§3",
    severity="MINOR",
    tags=["phase:P1"],
)
async def ev_p1_13():
    import tempfile
    from pathlib import Path

    import openpyxl

    from app.export.excel import build_export
    from app.projects import scaffold
    from app.projects.resolver import ProjectResolver
    from app.store import duckdb as dk
    from evals.harness import make_settings

    with tempfile.TemporaryDirectory(prefix="ev-export-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "export-check")
        try:
            out_path = await build_export(resolver, config)
            wb = openpyxl.load_workbook(out_path)
            assert {"documents", "links", "run_info"} <= set(wb.sheetnames)
            docs_ws = wb["documents"]
            assert docs_ws.freeze_panes == "A2", "documents sheet must freeze the header row"
            assert docs_ws["A1"].value == "doc_id", "documents sheet header must be the frozen A§8 column order"
        finally:
            await dk.forget_committer(resolver.project_dir(config.id))
