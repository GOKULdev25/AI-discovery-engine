"""EV-P0-03, 06, 07 — concurrency correctness in storage and job claiming."""

from __future__ import annotations

import asyncio
import uuid

from evals.harness import api_client, temp_project, wait_for_batch_done
from evals.registry import eval_case


@eval_case(
    "EV-P0-03",
    proves="Two projects extract concurrently without a DuckDB lock error",
    source="IP§0.3",
    severity="MAJOR",
    # `slow` (same reasoning as EV-P0-05/EV-P0-10, scripts/eval.py): two
    # concurrent DuckDB-committing batches, previously on
    # `wait_for_batch_done`'s tight 10s default — observed BLOCKED under
    # real machine memory pressure (30+ live Chrome tabs) even though
    # this eval does nothing slow by design.
    tags=["phase:P0", "slow"],
)
async def ev_p0_03():
    async with temp_project("p0-03-a") as (settings_a, resolver_a, project_a):
        async with temp_project("p0-03-b") as (settings_b, resolver_b, project_b):
            async with api_client(settings_a) as client_a, api_client(settings_b) as client_b:
                urls = [f"fixture://run?count=10&latency_ms=5&link={i}" for i in range(6)]
                resp_a = await client_a.post(f"/projects/{project_a}/batches", json={"urls": urls})
                resp_b = await client_b.post(f"/projects/{project_b}/batches", json={"urls": urls})
                batch_a, batch_b = resp_a.json()["batch_id"], resp_b.json()["batch_id"]

                await asyncio.gather(
                    wait_for_batch_done(client_a, project_a, batch_a, timeout=100),
                    wait_for_batch_done(client_b, project_b, batch_b, timeout=100),
                )

        from app.store import duckdb as dk

        reader_a = await dk.get_reader(resolver_a.project_dir(project_a))
        assert reader_a.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 60


@eval_case(
    "EV-P0-06",
    proves="A running job with a stale heartbeat returns to pending and completes",
    source="IP§0.4",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_06():
    from app.jobs import claim
    from app.store import sqlite as sq

    async with temp_project("p0-06") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        async with sq.ops_db(project_dir) as ops_conn:
            job_id = uuid.uuid4().hex
            await claim.enqueue_job(
                ops_conn, job_id=job_id, project_id=project_id, batch_id="b1",
                link_id="l1", connector_id="fixture", source="fixture",
                job_spec={"url": "fixture://run?count=1", "params": {}},
            )
            claimed = await claim.claim_next_job(ops_conn, "worker-doomed")
            assert claimed["id"] == job_id
            # Simulate a worker that claimed the job and then vanished, never
            # heartbeating again — reap_stale_claims must reclaim it.
            reaped = await claim.reap_stale_claims(ops_conn, stale_seconds=0)
            assert reaped == 1

            cur = await ops_conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
            row = await cur.fetchone()
            assert row["status"] == "pending", "stale job was not returned to pending"

            reclaimed = await claim.claim_next_job(ops_conn, "worker-2")
            assert reclaimed is not None and reclaimed["id"] == job_id


@eval_case(
    "EV-P0-07",
    proves="Job claiming is atomic under 8 concurrent workers — zero double-claims",
    source="IP§0.4",
    severity="BLOCKER",
    tags=["phase:P0"],
)
async def ev_p0_07():
    from app.jobs import claim
    from app.store import sqlite as sq

    async with temp_project("p0-07") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        n_jobs = 200
        async with sq.ops_db(project_dir) as seed_conn:
            for i in range(n_jobs):
                await claim.enqueue_job(
                    seed_conn, job_id=f"job-{i}", project_id=project_id, batch_id="b1",
                    link_id=f"l{i}", connector_id="fixture", source="fixture",
                    job_spec={"url": "fixture://run?count=1", "params": {}},
                )

        # 8 INDEPENDENT connections — this is what actually exercises SQLite's
        # own write serialization, not just aiosqlite's single-threaded queue
        # on one shared connection object.
        n_workers = 8
        worker_conns = [await sq.open_ops_db(project_dir) for _ in range(n_workers)]
        try:
            claimed_ids: list[str] = []

            async def drain(worker_idx: int) -> None:
                conn = worker_conns[worker_idx]
                while True:
                    job = await claim.claim_next_job(conn, f"w{worker_idx}")
                    if job is None:
                        return
                    claimed_ids.append(job["id"])

            await asyncio.gather(*(drain(i) for i in range(n_workers)))
        finally:
            for c in worker_conns:
                await c.close()

        assert len(claimed_ids) == n_jobs, f"expected {n_jobs} claims, got {len(claimed_ids)}"
        assert len(set(claimed_ids)) == n_jobs, "a job was claimed more than once"
