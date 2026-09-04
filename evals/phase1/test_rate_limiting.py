"""EV-P1-08, 09 — politeness is structural and actually observed, and
rate limits are shared globally across projects, not per-project
(A§10.2)."""

from __future__ import annotations

import asyncio
import time

from app.jobs.limits import LimiterRegistry, RateSpec, get_limiter_registry
from evals.registry import eval_case


@eval_case(
    "EV-P1-08",
    proves="The token bucket actually paces requests: observed intervals respect min_interval_s, jitter is distributed",
    source="A§10.2",
    severity="MAJOR",
    tags=["phase:P1"],
)
async def ev_p1_08():
    registry = LimiterRegistry({"test-source": RateSpec(concurrency=4, min_interval_s=0.05, jitter_s=0.05)})
    limiter = registry.for_source("test-source")

    timestamps = []
    for _ in range(6):
        async with limiter:
            timestamps.append(time.monotonic())

    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    assert all(g >= 0.05 - 0.005 for g in gaps), f"a gap was shorter than min_interval_s: {gaps}"
    # Jitter must actually vary the gap, not just add a constant — a
    # "structural" claim with no distribution behind it is exactly what
    # this eval exists to catch.
    assert len(set(round(g, 3) for g in gaps)) > 1, f"gaps look constant, not jittered: {gaps}"


@eval_case(
    "EV-P1-09",
    proves="Rate limits are global across projects: two projects hitting the same source share one budget",
    source="A§10.2",
    severity="BLOCKER",
    tags=["phase:P1"],
)
async def ev_p1_09():
    # The registry is a process-wide singleton specifically so two
    # ProjectEngines (different projects) constructing a Ctx for the same
    # source resolve to the identical SourceLimiter — same semaphore, same
    # bucket — regardless of which project asked for it.
    registry_a = get_limiter_registry()
    registry_b = get_limiter_registry()
    assert registry_a is registry_b, "get_limiter_registry() is not a process-wide singleton"

    limiter_a = registry_a.for_source("reddit")
    limiter_b = registry_b.for_source("reddit")
    assert limiter_a is limiter_b, "two lookups for the same source returned different limiters"

    # Concurrency bound is shared too: with concurrency=2, three
    # concurrent "projects" contending for the same source must see only
    # 2 in flight at once, never 3.
    registry = LimiterRegistry({"shared-source": RateSpec(concurrency=2, min_interval_s=0.0)})
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def hold(project_tag: str):
        nonlocal in_flight, max_in_flight
        limiter = registry.for_source("shared-source")  # every "project" resolves the same limiter
        async with limiter:
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1

    await asyncio.gather(*(hold(f"project-{i}") for i in range(5)))
    assert max_in_flight <= 2, f"concurrency bound was not shared across callers: saw {max_in_flight} in flight"
