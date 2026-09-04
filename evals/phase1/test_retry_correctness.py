"""EV-P1-16, 17 — retry re-classifies and re-expands a link instead of
trusting a bare JobSpec(url=...), and resets the batch's own status back
to 'running' when it re-queues work. Both found live, 2026-08-29:
retrying a real YouTube link crashed with `EXTRACTOR_CRASH: 'video_id'`
(only the fixture connector's `run()` re-parses its own URL, so every
other connector's reliance on match()-populated `params` went untested
by the fixture-only EV-P0-09), and the batch's `status` stayed stuck at
'done' while the retried link was genuinely back in flight.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.jobs.engine import forget_engine, retry_batch
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.registry import eval_case


@eval_case(
    "EV-P1-16",
    proves="Retry re-classifies and re-expands a link (match()+expand()), not a bare JobSpec(url=...) with empty params",
    source="A§8.1",
    severity="BLOCKER",
    tags=["phase:P1"],
)
async def ev_p1_16():
    with tempfile.TemporaryDirectory(prefix="ev-p116-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p116")
        project_dir = resolver.project_dir(config.id)
        try:
            # A real connector URL whose `run()` reads required params via
            # direct indexing (job.params["app_id"]) rather than fixture's
            # defensive `.get()` calls — the fixture connector's own
            # leniency is exactly why this bug shipped untested: it never
            # crashes on an empty params dict, so EV-P0-09's fixture-only
            # retry test couldn't have caught it. App Store, Play Store,
            # and YouTube all share this same required-params shape.
            url = "https://apps.apple.com/us/app/testapp/id123456789"
            batch_id, link_id = "b1", "l1"
            async with sq.ops_db(project_dir) as ops_conn:
                # Insert the failed-link state directly rather than going
                # through submit_batch(): that starts the project's real
                # worker pool, which would race to claim and actually
                # fetch this App Store URL live before the test gets a
                # chance to inspect anything — retry_batch() only needs a
                # batches/links row to exist, not a prior real run.
                now = "2026-08-29T00:00:00Z"
                await ops_conn.execute(
                    "INSERT INTO batches (id, project_id, status, created_at, updated_at, link_count) "
                    "VALUES (?, ?, 'done', ?, ?, 1)",
                    (batch_id, config.id, now, now),
                )
                await ops_conn.execute(
                    "INSERT INTO links (id, batch_id, project_id, url, connector_id, status, "
                    "failure_code, retryable, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'appstore', 'failed', 'NETWORK_ERROR', 1, ?, ?)",
                    (link_id, batch_id, config.id, url, now, now),
                )
                await ops_conn.commit()

            retried = await retry_batch(settings, config.id, batch_id)
            assert retried == 1
            # retry_batch() starts this project's real worker pool as its
            # last step, which would otherwise race to claim and actually
            # fetch this (fake) App Store URL live — stop it immediately.
            await forget_engine(config.id)

            async with sq.ops_db(project_dir) as ops_conn:
                cur = await ops_conn.execute(
                    "SELECT job_spec FROM jobs WHERE link_id = ? ORDER BY created_at DESC LIMIT 1", (link_id,)
                )
                row = await cur.fetchone()
            job_spec = json.loads(row["job_spec"])
            # Before the fix this was `{}` — a bare JobSpec(url=...) with
            # no params — and App Store's `run()` would KeyError on
            # `job.params["app_id"]` (observed live as YouTube's
            # `job.params["video_id"]`, the same shape).
            assert job_spec.get("params", {}).get("app_id") == "123456789", (
                f"retry enqueued a job with no re-classified params: {job_spec}"
            )
            assert job_spec.get("params", {}).get("country") in {"us", "in", "gb"}, (
                "retry must also re-run expand() — a locale fan-out link needs its params back too"
            )
        finally:
            await forget_engine(config.id)
            await dk.forget_committer(project_dir)


@eval_case(
    "EV-P1-17",
    proves="Retry resets the batch's own status back to 'running' — it must not still read 'done' while a link reprocesses",
    source="A§13",
    severity="MAJOR",
    tags=["phase:P1"],
)
async def ev_p1_17():
    with tempfile.TemporaryDirectory(prefix="ev-p117-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p117")
        project_dir = resolver.project_dir(config.id)
        try:
            # Inserted directly rather than via submit_batch(), which
            # would start this project's real worker pool racing to
            # process the job before the test gets to set up the
            # "already done" batch state it wants to check against.
            url = "fixture://run?count=1&latency_ms=0"
            batch_id, link_id = "b1", "l1"
            now = "2026-08-29T00:00:00Z"
            async with sq.ops_db(project_dir) as ops_conn:
                await ops_conn.execute(
                    "INSERT INTO batches (id, project_id, status, created_at, updated_at, link_count) "
                    "VALUES (?, ?, 'done', ?, ?, 1)",
                    (batch_id, config.id, now, now),
                )
                await ops_conn.execute(
                    "INSERT INTO links (id, batch_id, project_id, url, connector_id, status, "
                    "failure_code, retryable, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'fixture', 'failed', 'NETWORK_ERROR', 1, ?, ?)",
                    (link_id, batch_id, config.id, url, now, now),
                )
                await ops_conn.commit()

            retried = await retry_batch(settings, config.id, batch_id)
            assert retried == 1
            await forget_engine(config.id)  # stop before it claims/runs the newly-enqueued job

            async with sq.ops_db(project_dir) as ops_conn:
                cur = await ops_conn.execute("SELECT status FROM batches WHERE id=?", (batch_id,))
                row = await cur.fetchone()
            assert row["status"] == "running", (
                f"batch status must reset to 'running' when retry re-queues work, still shows {row['status']!r}"
            )
        finally:
            await forget_engine(config.id)
            await dk.forget_committer(project_dir)
