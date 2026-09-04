"""EV-P3-05, 06, 07, 12 — the quota ledger itself: genuinely shared across
callers, durable across a restart, correct at rolling-window boundaries,
and visible through the API before a batch spends it (A§7.3)."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.ai import quota
from app.ai.providers.base import ProviderLimits, ProviderQuotaExhausted
from app.store import sqlite as sq
from evals.harness import api_client, make_settings
from evals.registry import eval_case


async def _attempt(app_sqlite: Path, provider_id: str, limits: ProviderLimits) -> bool:
    async with sq.app_db(app_sqlite) as conn:
        try:
            await quota.reserve(conn, provider_id, limits, 1)
            return True
        except ProviderQuotaExhausted:
            return False


@eval_case(
    "EV-P3-05",
    proves="The quota pool is genuinely shared: concurrent callers (standing in for two projects) never draw more than one ceiling's worth",
    source="A§7.3",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_05():
    limits = ProviderLimits(rpm=3, tpm=None, rpd=None)
    with tempfile.TemporaryDirectory(prefix="ev-p305-") as tmp:
        app_sqlite = Path(tmp) / "app.sqlite"
        async with sq.app_db(app_sqlite):
            pass  # apply migrations once, up front, so the concurrent phase below only races on quota_ledger rows

        # Two "projects" (six independent callers, each its own
        # connection — exactly how two real ProjectEngines would each
        # open their own app.sqlite connection) hammering the same
        # provider concurrently.
        results = await asyncio.gather(*[_attempt(app_sqlite, "gemini", limits) for _ in range(6)])
        successes = sum(1 for r in results if r)
        assert successes == 3, (
            f"a ceiling of 3 shared across 6 concurrent callers should allow exactly 3 successes, got {successes} — "
            "if this is 6, the pool was accidentally scoped per-caller instead of shared"
        )


@eval_case(
    "EV-P3-06",
    proves="Usage recorded before a kill is still counted after — a ledger that resets on restart would silently overspend the real ceiling",
    source="A§7.3",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_06():
    limits = ProviderLimits(rpm=5, tpm=None, rpd=None)
    with tempfile.TemporaryDirectory(prefix="ev-p306-") as tmp:
        app_sqlite = Path(tmp) / "app.sqlite"
        async with sq.app_db(app_sqlite) as conn:
            await quota.reserve(conn, "gemini", limits, 1)
            await quota.reserve(conn, "gemini", limits, 1)
        # Connection closed here — simulates the process being killed and
        # a fresh one opening `app.sqlite` on restart.
        async with sq.app_db(app_sqlite) as conn:
            remaining = await quota.remaining(conn, "gemini", limits)
        assert remaining["rpm"]["used"] == 2, (
            f"expected the 2 reservations made before the 'restart' to survive it, got used={remaining['rpm']['used']}"
        )


@eval_case(
    "EV-P3-07",
    proves="Rolling-window arithmetic is correct at RPM/RPD boundaries: no off-by-one admitting an over-limit call, no false starvation across the boundary",
    source="A§11.1",
    severity="MAJOR",
    tags=["phase:P3"],
)
async def ev_p3_07():
    rpm_limits = ProviderLimits(rpm=3, tpm=None, rpd=None)
    with tempfile.TemporaryDirectory(prefix="ev-p307-") as tmp:
        app_sqlite = Path(tmp) / "app.sqlite"
        base = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
        async with sq.app_db(app_sqlite) as conn:
            for _ in range(3):
                await quota.reserve(conn, "gemini", rpm_limits, 1, now=base)

            async def _fails_at(when: datetime) -> bool:
                try:
                    await quota.reserve(conn, "gemini", rpm_limits, 1, now=when)
                    return False
                except ProviderQuotaExhausted:
                    return True

            assert await _fails_at(base), "the 4th reservation in the same minute must be refused — no off-by-one"
            assert await _fails_at(base + timedelta(seconds=1)), "the window must not reset before the minute actually rolls over"

            next_minute = (base + timedelta(minutes=1)).replace(second=0, microsecond=0)
            assert not await _fails_at(next_minute), "a genuinely new minute must not be falsely starved by the previous window"

        rpd_limits = ProviderLimits(rpm=None, tpm=None, rpd=2)
        async with sq.app_db(app_sqlite) as conn:
            end_of_day = datetime(2026, 1, 1, 23, 59, 0, tzinfo=timezone.utc)
            await quota.reserve(conn, "groq", rpd_limits, 1, now=end_of_day)
            await quota.reserve(conn, "groq", rpd_limits, 1, now=end_of_day)
            try:
                await quota.reserve(conn, "groq", rpd_limits, 1, now=end_of_day)
                assert False, "the 3rd reservation against a daily limit of 2 must be refused"
            except ProviderQuotaExhausted:
                pass

            next_day = datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc)
            await quota.reserve(conn, "groq", rpd_limits, 1, now=next_day)  # must not raise


@eval_case(
    "EV-P3-12",
    proves="GET /quota reports remaining daily budget before a batch starts, and reflects usage as it's spent",
    source="A§7.3",
    severity="MAJOR",
    tags=["phase:P3"],
)
async def ev_p3_12():
    with tempfile.TemporaryDirectory(prefix="ev-p312-") as tmp:
        settings = make_settings(Path(tmp))
        async with api_client(settings) as client:
            resp = await client.get("/quota")
            assert resp.status_code == 200
            body = resp.json()
            for provider_id in ("gemini", "groq", "ollama"):
                assert provider_id in body
                for window_kind in ("rpm", "tpm", "rpd"):
                    assert window_kind in body[provider_id]
            assert body["gemini"]["rpd"]["remaining"] == body["gemini"]["rpd"]["limit"], "budget must be fully visible and unspent before any batch runs"

            from app.ai.providers.gemini import LIMITS as GEMINI_LIMITS

            async with sq.app_db(settings.app_sqlite_path) as conn:
                await quota.reserve(conn, "gemini", GEMINI_LIMITS, 1000)

            resp2 = await client.get("/quota")
            body2 = resp2.json()
            assert body2["gemini"]["rpd"]["used"] == 1, "a spent request must be reflected in the budget the API reports"
            assert body2["gemini"]["tpm"]["used"] == 1000
