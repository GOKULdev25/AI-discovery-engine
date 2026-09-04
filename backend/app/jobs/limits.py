"""Per-source semaphore + token bucket with jitter (A§10.2). Limits are
process-wide singletons, not per-project — two projects hitting Reddit at
once still share Reddit's one QPM budget, since the rate limit belongs to
the remote service (EV-P1-09 exercises this from Phase 1 onward).

Phase 0 wires this up for the `fixture` source too, so the fake connector
exercises the exact same politeness path every real connector will use
in Phase 1 — nothing here is fixture-only scaffolding.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass


@dataclass
class RateSpec:
    concurrency: int
    min_interval_s: float  # minimum gap between requests, before jitter
    jitter_s: float = 0.0  # up to this much extra random delay


# A§10.2 defaults. `browser` is a structural ceiling of 1 — never raised
# (A§4) — everything else is a starting point, overridable per project via
# `project.yaml` rate_overrides (read by whatever constructs this registry
# at startup, not by editing this table).
DEFAULT_RATE_SPECS: dict[str, RateSpec] = {
    "youtube": RateSpec(concurrency=4, min_interval_s=0.05),
    "appstore": RateSpec(concurrency=3, min_interval_s=1.0),
    "reddit": RateSpec(concurrency=2, min_interval_s=0.6, jitter_s=0.2),
    "playstore": RateSpec(concurrency=2, min_interval_s=1.5, jitter_s=1.5),
    "browser": RateSpec(concurrency=1, min_interval_s=3.0, jitter_s=5.0),
    # Lane 3 (A§4): one shared budget across every distinct arbitrary
    # domain this lane ever touches, since the id (and therefore the
    # limiter key) is the connector, not the target site — deliberately
    # conservative, since nothing here knows this domain's own norms.
    "llm_dom": RateSpec(concurrency=2, min_interval_s=0.5, jitter_s=0.5),
    "fixture": RateSpec(concurrency=8, min_interval_s=0.0),
}


class TokenBucket:
    """Serializes calls for one source to at least `min_interval_s` apart,
    plus up to `jitter_s` of randomized extra delay — observed intervals
    are what EV-P1-08 checks, so jitter must be real, not a comment."""

    def __init__(self, spec: RateSpec):
        self._spec = spec
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            delay = self._spec.min_interval_s - elapsed
            if self._spec.jitter_s > 0:
                delay += random.uniform(0, self._spec.jitter_s)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_call = time.monotonic()


class SourceLimiter:
    def __init__(self, spec: RateSpec):
        self.semaphore = asyncio.Semaphore(spec.concurrency)
        self.bucket = TokenBucket(spec)

    async def __aenter__(self) -> "SourceLimiter":
        await self.semaphore.acquire()
        await self.bucket.wait()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.semaphore.release()


class LimiterRegistry:
    """Process-wide singleton — this is what makes limits global across
    projects rather than per-project (A§10.2)."""

    def __init__(self, specs: dict[str, RateSpec] | None = None):
        self._specs = dict(specs or DEFAULT_RATE_SPECS)
        self._limiters: dict[str, SourceLimiter] = {}

    def for_source(self, source: str) -> SourceLimiter:
        if source not in self._limiters:
            spec = self._specs.get(source, RateSpec(concurrency=1, min_interval_s=1.0))
            self._limiters[source] = SourceLimiter(spec)
        return self._limiters[source]


_registry = LimiterRegistry()


def get_limiter_registry() -> LimiterRegistry:
    return _registry
