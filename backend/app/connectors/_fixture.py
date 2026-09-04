"""The fake connector (IP§0.8). Matches `fixture://...` URLs and emits N
synthetic documents with configurable latency and a configurable failure
at document K. This is how Phase 0's gate is testable with zero network,
and it stays in the repo permanently as the job engine's test harness.

URL shape: fixture://run?count=50&latency_ms=5&fail_at=10&fail_code=PARSE_ERROR
- count: how many docs to emit total
- latency_ms: simulated per-doc work time
- fail_at: 1-indexed doc number to fail at instead of emitting (optional)
- fail_code: one of the A§8.1 taxonomy codes (default PARSE_ERROR)
- bug=1: raise a plain RuntimeError at `fail_at` instead of a typed
  ExtractionError — exercises the EXTRACTOR_CRASH boundary (EV-INV-12)
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app.connectors.base import Ctx, Doc, JobSpec
from app.jobs.failures import ExtractionError, FailureCode

EXTRACTOR_VERSION = "fixture-1"


class FixtureConnector:
    id = "fixture"
    lane = "api"

    def match(self, url: str) -> JobSpec | None:
        parsed = urlparse(url)
        if parsed.scheme != "fixture":
            return None
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return JobSpec(url=url, params=params)

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        return [job]

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        params = job.params
        count = int(params.get("count", 10))
        latency_ms = float(params.get("latency_ms", 0))
        fail_at = int(params["fail_at"]) if "fail_at" in params else None
        fail_code = FailureCode(params.get("fail_code", FailureCode.PARSE_ERROR.value))
        bug = params.get("bug") == "1"

        start_at = 1
        checkpoint_cursor = params.get("_resume_after")
        if checkpoint_cursor:
            start_at = int(checkpoint_cursor) + 1

        for i in range(start_at, count + 1):
            if ctx.signal.is_set():
                return
            if latency_ms:
                await asyncio.sleep(latency_ms / 1000)
            if fail_at is not None and i == fail_at:
                if bug:
                    raise RuntimeError(f"simulated extractor bug at doc {i}")
                raise ExtractionError(fail_code, f"fixture configured to fail at doc {i}")

            doc_id = hashlib.sha256(f"{job.url}|{i}".encode()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            yield Doc(
                doc_id=doc_id,
                source="fixture",
                doc_type="review",
                source_url=job.url,
                captured_at=now,
                lane=self.lane,
                extractor_version=EXTRACTOR_VERSION,
                raw={"i": i, "url": job.url},
                text=f"synthetic fixture document {i}",
                author_hash=hashlib.sha256(f"author-{i}".encode()).hexdigest(),
            )
            await ctx.checkpoint(str(i))
