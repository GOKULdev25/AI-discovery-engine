"""EV-P6-03, 04 — human pacing is measured, not intended (A§4: "a
correctness requirement, not politeness theater"), and the browser lane
is never parallel. Same mechanism Phase 1 already proved generically
(EV-P1-08/09's `SourceLimiter`) — what's new here is confirming the
`browser` source's own configured spec actually matches "3-8s, one tab."
"""

from __future__ import annotations

import asyncio
import time

from app.jobs.limits import DEFAULT_RATE_SPECS, LimiterRegistry, RateSpec
from evals.registry import eval_case


@eval_case(
    "EV-P6-03",
    proves="Recorded navigation timings: every gap in 3-8s, distribution non-constant, never two pages in the same second",
    source="A§4",
    severity="BLOCKER",
    tags=["phase:P6"],
)
async def ev_p6_03():
    browser_spec = DEFAULT_RATE_SPECS["browser"]
    assert browser_spec.min_interval_s == 3.0, f"browser's minimum pacing must be 3s, got {browser_spec.min_interval_s}"
    assert browser_spec.jitter_s == 5.0, f"browser's jitter must extend the range to 8s (3+5), got jitter={browser_spec.jitter_s}"
    assert browser_spec.concurrency == 1, "one tab means concurrency=1"

    # A scaled-down spec of the same *shape* (Phase 1's own pattern,
    # EV-P1-08) — proving the mechanism produces genuinely jittered,
    # non-constant, always-above-minimum gaps without spending a real
    # 3-8s x N in this eval.
    registry = LimiterRegistry({"browser-shape": RateSpec(concurrency=1, min_interval_s=0.3, jitter_s=0.5)})
    limiter = registry.for_source("browser-shape")

    timestamps = []
    for _ in range(6):
        async with limiter:
            timestamps.append(time.monotonic())

    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    assert all(g >= 0.3 - 0.02 for g in gaps), f"a gap was shorter than the minimum: {gaps}"
    assert all(g <= 0.3 + 0.5 + 0.05 for g in gaps), f"a gap exceeded min+jitter: {gaps}"
    assert len(set(round(g, 2) for g in gaps)) > 1, f"gaps look constant, not jittered: {gaps}"
    # "Never two pages in the same second" — the minimum alone guarantees
    # this for the real 3s spec; confirm no gap ever collapses toward 0.
    assert all(g > 0.1 for g in gaps), f"a gap was suspiciously close to simultaneous: {gaps}"


@eval_case(
    "EV-P6-04",
    proves="Concurrency for lane 2 is exactly 1; one tab; asserted under load",
    source="A§10.2",
    severity="BLOCKER",
    tags=["phase:P6"],
)
async def ev_p6_04():
    assert DEFAULT_RATE_SPECS["browser"].concurrency == 1, "browser concurrency is a structural ceiling of 1 (A§4) — never raised"

    registry = LimiterRegistry({"browser": RateSpec(concurrency=1, min_interval_s=0.0)})
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def hold():
        nonlocal in_flight, max_in_flight
        limiter = registry.for_source("browser")
        async with limiter:
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1

    # Ten concurrent "jobs" (standing in for ten links across one or more
    # projects — the limiter is process-wide, A§10.2) hammering the
    # browser source at once.
    await asyncio.gather(*(hold() for _ in range(10)))
    assert max_in_flight == 1, f"the browser lane must never run more than one tab at a time, saw {max_in_flight}"
