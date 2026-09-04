"""EV-P6-01, 02 — Flipkart reviews extract correctly from a recorded
session at human pace with visible per-link progress, and zero CSS/XPath
selectors exist anywhere in the extraction path (EVAL.md §6.8: "Browser
evals run against recorded sessions in the automatic suite").

The "recorded session" here is a real captured Flipkart review page's
rendered text (Docs/FEASIBILITY_LOG.md, 2026-08-30) replayed through a
real Playwright browser via `context.route()` — the actual connector
code runs unmodified; only the network response is canned.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
from pathlib import Path

from app.browser import session as browser_session
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import sqlite as sq
from evals.harness import BACKEND_APP_DIR, make_settings
from evals.registry import eval_case

# A real captured Flipkart review page's rendered text, line for line
# (Docs/FEASIBILITY_LOG.md, 2026-08-30) — three real reviews, verbatim.
_RECORDED_REVIEW_LINES = [
    "3.0", "•", "Decent product",
    "Review for: Color Midnight Blue • Microphone Yes",
    "At starting battery backup was pretty good",
    "But after use of 1 month battery drained  quickly.. disappointed with the claims mentioned in product details 😑",
    "Mahindra  Chapagai", ", New Delhi", "Helpful for 730", "290", "Verified Purchase", "· Dec, 2024",
    "3.0", "•", "Good",
    "Review for: Color Midnight Black • Microphone Yes",
    "Don't purchase if you want to watch lectures on it. Better go for neckbands or expensive earbuds. you have to keep charging it after ever 4 to 6 hr.",
    "Flipkart Customer", ", Lucknow", "Helpful for 262", "95", "Verified Purchase", "· Jan, 2025",
    "4.0", "•", "Really Nice",
    "Review for: Color Ivory White • Microphone Yes",
    "Nice good",
    "Sumit Hira", ", Raighar", "Helpful for 164", "76", "Verified Purchase", "· May, 2024",
]

_RECORDED_HTML = "<html><body>\n" + "\n".join(f"<div>{ln}</div>" for ln in _RECORDED_REVIEW_LINES) + "\n</body></html>"


@eval_case(
    "EV-P6-01",
    proves="Flipkart reviews extract from a recorded session at human pace, with per-link progress visible like any other lane",
    source="A§2.1",
    severity="MAJOR",
    tags=["phase:P6"],
)
async def ev_p6_01():
    with tempfile.TemporaryDirectory(prefix="ev-p601-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p601")
        project_dir = resolver.project_dir(config.id)
        try:
            context = await browser_session.get_context(project_dir, session_mode="logged_out", headless=True)

            async def handler(route):
                await route.fulfill(body=_RECORDED_HTML, content_type="text/html")

            await context.route("**/product-reviews/**", handler)
            # `flipkart.py` also fetches the plain product page for its
            # Q&A preview (P7) before ever touching reviews — without a
            # route for it too, that fetch would fall through to a real,
            # live network request (EV-INV-14). `_RECORDED_HTML` has no
            # Q&A widget markers, so this correctly yields zero Q&A rows,
            # leaving this eval's review count exactly as before.
            await context.route("**/p/**", handler)

            from app.jobs.engine import submit_batch

            product_url = (
                "https://www.flipkart.com/some-earbuds/p/itmc760b699706b1"
                "?pid=ACCHGAHMURK4ZHPK&lid=LSTACCHGAHMURK4ZHPKSCT0TV"
            )
            batch_id, links = await submit_batch(settings, config.id, [product_url])
            assert links[0]["status"] == "pending"

            async with sq.ops_db(project_dir) as ops_conn:
                deadline = time.monotonic() + 30
                status = None
                while time.monotonic() < deadline:
                    cur = await ops_conn.execute("SELECT status FROM batches WHERE id = ?", (batch_id,))
                    row = await cur.fetchone()
                    status = row["status"]
                    if status == "done":
                        break
                    await asyncio.sleep(0.2)
                assert status == "done", f"batch never completed, last status: {status}"

                cur = await ops_conn.execute(
                    "SELECT event_type, payload FROM events WHERE batch_id = ? AND event_type = 'link.docs'", (batch_id,)
                )
                progress_events = await cur.fetchall()
                assert progress_events, "per-link progress (link.docs) must be visible, not silent, for the browser lane too"

            from app.store import duckdb as dk

            reader = await dk.get_reader(project_dir)
            docs = reader.execute(
                "SELECT text, rating, verified_purchase FROM documents WHERE project_id = ? ORDER BY rating", [config.id]
            ).fetchall()
            assert len(docs) == 3, f"expected exactly the 3 recorded reviews, got {len(docs)}"
            texts = " ".join(d[0] for d in docs)
            assert "Decent product" in texts and "Really Nice" in texts and "Good" in texts
            assert all(d[2] is True for d in docs), "all 3 recorded reviews were Verified Purchase"
        finally:
            from app.jobs.engine import forget_engine

            await forget_engine(config.id)
            # close_all(), not just close_context() — this eval process's
            # module-level `_playwright` singleton is bound to *this*
            # asyncio.run()'s event loop. Leaving it alive breaks the next
            # eval, which gets a fresh loop from a fresh asyncio.run().
            await browser_session.close_all()


_SELECTOR_MARKERS = re.compile(
    # Actual selector-usage code patterns, not the bare words "CSS"/
    # "selector"/"XPath" — this file's own docstrings legitimately use
    # those words while explaining that none of these are used, which
    # must not self-flag.
    r"query_selector|css_selector|page\.locator\(|find_element|xpath=|\.xpath\(|\.select_one\(|BeautifulSoup|soupsieve",
    re.IGNORECASE,
)


@eval_case(
    "EV-P6-02",
    proves="Zero CSS/XPath selector-based extraction anywhere in the Flipkart path",
    source="A§4",
    severity="BLOCKER",
    tags=["phase:P6"],
)
def ev_p6_02():
    checked = [
        BACKEND_APP_DIR / "browser" / "sites" / "flipkart.py",
        BACKEND_APP_DIR / "browser" / "sites" / "amazon.py",
        BACKEND_APP_DIR / "browser" / "text_extract.py",
    ]
    hits = []
    for path in checked:
        text = path.read_text(encoding="utf-8")
        if _SELECTOR_MARKERS.search(text):
            hits.append(str(path))
    assert not hits, f"selector-based extraction found where none should exist: {hits}"
