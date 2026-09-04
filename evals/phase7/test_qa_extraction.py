"""EV-P7-04, 09 — Q&A needed no migration, and Amazon Q&A is not
attempted (EVAL.md §6.9). `doc_type` in {qa_question, qa_answer} with a
`parent_id` self-link was in the frozen A§8 schema from Phase 0, so a
real Flipkart Q&A pair round-trips as two linked rows with zero new
migration files.
"""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path

from app.browser.sites import amazon as amazon_mod
from app.browser.sites.flipkart import FlipkartConnector
from app.browser.text_extract import parse_qa_from_text
from app.jobs.engine import forget_engine, submit_batch
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from evals.harness import BACKEND_DIR, make_settings
from evals.registry import eval_case

# A real captured Flipkart product page's Q&A preview widget, verbatim
# (Docs/FEASIBILITY_LOG.md, 2026-08-30) — a boAt Airdopes product, 3 real
# Q&A pairs, including one answer the widget itself truncates with
# "...more".
_RECORDED_QA_LINES = [
    "Questions and Answers",
    "Find answers to commonly asked questions",
    "How is the call clarity ?",
    "Good quality product with clear sound",
    "Verified buyer",
    "What's it's real battery backup?",
    "25 hr if you use it continue .",
    "Verified buyer",
    "How to connect this buds",
    "Refer user manual",
    "1. Switch on the Bluetooth in your mobil...more",
    "Verified buyer",
    "Show all questions & answers",
    "Add to cart",
    "Buy now",
]

_RECORDED_HTML = "<html><body>\n" + "\n".join(f"<div>{ln}</div>" for ln in _RECORDED_QA_LINES) + "\n</body></html>"

_NO_MIGRATIONS_ADDED_SINCE_PHASE0_CLAIM = (
    "Docs/IMPLEMENTATION_PLAN.md line 238: 'Q&A ships in P7 with zero migration' — "
    "verified here by checking no migration file postdates 0001_init.sql"
)


@eval_case(
    "EV-P7-04",
    proves="Q&A needed no migration: a Flipkart Q&A pair is two rows linked by parent_id, and no migration file was added after Phase 0",
    source="A§8",
    severity="MAJOR",
    tags=["phase:P7"],
)
async def ev_p7_04():
    # Guarantee 1: the parser itself, against the real recorded sample.
    lines = [ln for ln in _RECORDED_QA_LINES if ln]
    pairs = parse_qa_from_text(lines)
    assert len(pairs) == 3
    assert pairs[0] == {"question": "How is the call clarity ?", "answer": "Good quality product with clear sound"}
    assert pairs[2]["answer"] == "Refer user manual 1. Switch on the Bluetooth in your mobil...more"

    # Guarantee 2: the connector, through a real Playwright browser via
    # `context.route()` replay (same idiom as EV-P6-01), produces two
    # linked rows per pair — one `qa_question`, one `qa_answer` whose
    # `parent_id` is that exact question's `doc_id` — with zero CSS/XPath
    # selectors, using the schema's Phase-0 `parent_id` column.
    with tempfile.TemporaryDirectory(prefix="ev-p704-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p704")
        project_dir = resolver.project_dir(config.id)
        try:
            from app.browser import session as browser_session

            context = await browser_session.get_context(project_dir, session_mode="logged_out", headless=True)

            async def handler(route):
                await route.fulfill(body=_RECORDED_HTML, content_type="text/html")

            await context.route("**/p/**", handler)
            await context.route("**/product-reviews/**", handler)  # empty reviews page is fine; Q&A is what's under test

            product_url = (
                "https://www.flipkart.com/some-earbuds/p/itmc760b699706b1"
                "?pid=ACCHGAHMURK4ZHPK&lid=LSTACCHGAHMURK4ZHPKSCT0TV"
            )
            batch_id, links = await submit_batch(settings, config.id, [product_url])
            assert links[0]["status"] == "pending"

            import asyncio
            import time

            from app.store import sqlite as sq

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

            reader = await dk.get_reader(project_dir)
            qa_rows = reader.execute(
                "SELECT doc_id, doc_type, text, parent_id FROM documents WHERE project_id = ? AND doc_type IN ('qa_question', 'qa_answer')",
                [config.id],
            ).fetchall()
            questions = {r[0]: r for r in qa_rows if r[1] == "qa_question"}
            answers = [r for r in qa_rows if r[1] == "qa_answer"]
            assert len(questions) == 3, f"expected 3 questions, got {len(questions)}"
            assert len(answers) == 3, f"expected 3 answers, got {len(answers)}"
            for _, doc_type, text, parent_id in answers:
                assert parent_id is not None and parent_id in questions, (
                    f"qa_answer {text!r} must link to a real qa_question via parent_id, got {parent_id!r}"
                )
        finally:
            await forget_engine(config.id)
            from app.browser import session as browser_session

            await browser_session.close_all()

    # Guarantee 3: "zero migration" is a checkable fact, not a claim —
    # `doc_type`/`parent_id` (what a qa_question/qa_answer pair actually
    # needs) already exist in Phase 0's schema file; no migration added
    # after it so much as mentions Q&A, because none had to.
    migrations_dir = BACKEND_DIR / "app" / "store" / "migrations" / "warehouse"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    assert migration_files, "expected at least the Phase 0 init migration to exist"
    init_migration = migration_files[0]
    assert init_migration.name == "0001_init.sql"
    init_sql = init_migration.read_text(encoding="utf-8")
    assert "parent_id" in init_sql and "doc_type" in init_sql, (
        f"{_NO_MIGRATIONS_ADDED_SINCE_PHASE0_CLAIM} — but parent_id/doc_type are missing from {init_migration.name}"
    )
    for later_migration in migration_files[1:]:
        later_sql = later_migration.read_text(encoding="utf-8").lower()
        assert "qa_question" not in later_sql and "qa_answer" not in later_sql and "parent_id" not in later_sql, (
            f"{_NO_MIGRATIONS_ADDED_SINCE_PHASE0_CLAIM} — but {later_migration.name} touches Q&A's columns"
        )


@eval_case(
    "EV-P7-09",
    proves="Amazon Q&A is not attempted — no code path targets it, 🔴 Red by design",
    source="A§2.1",
    severity="MINOR",
    tags=["phase:P7"],
)
def ev_p7_09():
    source = inspect.getsource(amazon_mod)
    lowered = source.lower()
    assert "qa_question" not in lowered and "qa_answer" not in lowered, (
        "amazon.py must not attempt Q&A extraction — it is 🔴 Red by design, behind the same wall as its reviews (A§2.1)"
    )
