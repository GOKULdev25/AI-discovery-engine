"""EV-P0-05 — killing the backend mid-batch and restarting resumes from
the last checkpoint, losing no completed work and creating no duplicates
(A§10.3)."""

from __future__ import annotations

import asyncio

from evals.harness import api_client, temp_project, wait_for_batch_done
from evals.registry import eval_case


@eval_case(
    "EV-P0-05",
    proves="Killing the backend mid-batch and restarting resumes from the last checkpoint, not from scratch",
    source="A§10.3",
    severity="BLOCKER",
    # `slow` (same reasoning as EV-P0-10, scripts/eval.py): its own
    # internal `wait_for_batch_done(timeout=30)` left zero margin against
    # the ordinary 30s per-eval budget even before any real machine load
    # — observed BLOCKED under real memory pressure (30+ live Chrome
    # tabs) at 37.6s in the full suite despite passing standalone in 23s.
    tags=["phase:P0", "slow"],
)
async def ev_p0_05():
    from app.jobs import claim as claim_mod
    from app.jobs import engine as job_engine
    from app.store import duckdb as dk
    from app.store import sqlite as sq

    async with temp_project("p0-05", worker_count=2) as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)

        async with api_client(settings) as client:
            urls = [f"fixture://run?count=40&latency_ms=15&link={i}" for i in range(6)]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            batch_id = resp.json()["batch_id"]

            # Let real progress happen, then kill the process's in-memory
            # state the way a real crash would: workers vanish mid-flight,
            # nothing gets to finish or clean up.
            await asyncio.sleep(0.6)
            await job_engine.forget_engine(project_id)

            async with sq.ops_db(project_dir) as ops_conn:
                cur = await ops_conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status")
                mid_crash = {r["status"]: r["c"] for r in await cur.fetchall()}
                assert mid_crash.get("running", 0) > 0 or mid_crash.get("done", 0) < 6, (
                    "the batch finished before the simulated crash — test doesn't exercise resume"
                )

                # "Restart": force-reap anything the crash left stranded (what
                # the real reaper does on a timer) and resume processing —
                # exactly what main.py's lifespan startup does automatically.
                await claim_mod.reap_stale_claims(ops_conn, stale_seconds=0)

            await job_engine.resume_active_projects(settings)

            final = await wait_for_batch_done(client, project_id, batch_id, timeout=60)
            assert final["counts"] == {"done": 6}

        reader = await dk.get_reader(project_dir)
        total = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        distinct = reader.execute("SELECT COUNT(DISTINCT doc_id) FROM documents").fetchone()[0]
        assert total == 240, f"expected 6*40=240 documents, got {total} (crash resume lost or duplicated work)"
        assert distinct == 240, "duplicate doc_ids after resume — a job was double-processed"
