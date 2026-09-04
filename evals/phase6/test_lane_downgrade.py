"""EV-P6-07 — a Lane 1 -> Lane 2 downgrade is visible in the UI, never a
silent log line (A§4). Checked at classification/enqueue time only —
`forget_engine` stops the worker pool immediately after, before it can
claim and actually run the browser-lane job (this codebase's established
offline idiom for inspecting enqueue-time state, EV-INV-14)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.jobs.engine import forget_engine, submit_batch
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.registry import eval_case


@eval_case(
    "EV-P6-07",
    proves="A Lane 1 -> Lane 2 downgrade emits LANE_DOWNGRADE to the UI, not just a log",
    source="A§4",
    severity="MAJOR",
    tags=["phase:P6"],
)
async def ev_p6_07():
    with tempfile.TemporaryDirectory(prefix="ev-p607-") as tmp:
        settings = make_settings(Path(tmp))

        from app.projects import scaffold
        from app.projects.resolver import ProjectResolver

        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p607")
        project_dir = resolver.project_dir(config.id)
        # One batch, one engine lifecycle: a Lane 2 URL (Flipkart) and a
        # Lane 1 URL (fixture, standing in for a real green-source
        # connector) submitted together, so only one classify+enqueue
        # pass and one forget_engine() are needed — fewer engine
        # start/stop transitions than two separate batches, and this
        # eval only ever inspects classification/enqueue-time state
        # anyway (EV-INV-14's offline idiom), never runtime behavior.
        flipkart_url = (
            "https://www.flipkart.com/some-earbuds/p/itmc760b699706b1"
            "?pid=ACCHGAHMURK4ZHPK&lid=LSTACCHGAHMURK4ZHPKSCT0TV"
        )
        fixture_url = "fixture://run?count=1&latency_ms=0"
        try:
            batch_id, links = await submit_batch(settings, config.id, [flipkart_url, fixture_url])
            assert links[0]["status"] == "pending" and links[1]["status"] == "pending"
        finally:
            await forget_engine(config.id)  # stop before any worker claims/runs a job — no real browser, no real network

        async with sq.ops_db(project_dir) as ops_conn:
            cur = await ops_conn.execute(
                "SELECT event_type, payload FROM events WHERE batch_id = ? AND event_type = 'lane.downgrade'", (batch_id,)
            )
            rows = await cur.fetchall()

        assert len(rows) == 1, f"exactly the Flipkart link should be reported as a downgrade, got {len(rows)} event(s)"
        import json

        payload = json.loads(rows[0]["payload"])
        assert payload["from_lane"] == "api" and payload["to_lane"] == "browser"
        assert payload["url"] == flipkart_url, "the fixture (Lane 1) URL must never be reported as a downgrade"
