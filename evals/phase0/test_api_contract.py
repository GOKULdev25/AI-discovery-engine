"""EV-P0-14 — submitting a batch never blocks on extraction (A§13)."""

from __future__ import annotations

import time

from evals.harness import api_client, temp_project
from evals.registry import eval_case


@eval_case(
    "EV-P0-14",
    proves="POST /batches returns a batch_id in <200ms with links written pending",
    source="A§13",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_14():
    async with temp_project("p0-14") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            # Deliberately slow-and-numerous so the request would take
            # seconds if submission waited on extraction instead of just
            # classification + row-writing.
            urls = [f"fixture://run?count=100&latency_ms=200&link={i}" for i in range(20)]
            t0 = time.monotonic()
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            elapsed = time.monotonic() - t0

            assert resp.status_code == 202
            assert elapsed < 0.2, f"POST /batches took {elapsed:.3f}s — it must not block on extraction"
            links = resp.json()["links"]
            assert all(l["status"] == "pending" for l in links)
