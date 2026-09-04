"""The app-level quota ledger (A§7.3 🔒) — `data/app.sqlite`, shared by
every project, because Gemini's daily limit attaches to the API key, not
to any one research question. `ai/router.py` calls `reserve()` before
every provider call and `record_actual()` after, so the ledger's numbers
end up matching the providers' own (Phase 3 gate).

Reservation across all three windows (RPM/TPM/RPD) is all-or-nothing:
several `UPDATE ... WHERE used + ? <= limit` statements share one
uncommitted transaction (the same multi-statement-then-single-commit
idiom `jobs/engine.py::submit_batch` already uses), and if any window
would be exceeded the whole transaction rolls back rather than partially
consuming the other two. WAL mode still serializes writers process-wide
even before commit, so this is correct under concurrent connections
without needing an explicit `BEGIN IMMEDIATE` (jobs/claim.py's atomic
`UPDATE ... RETURNING` is the same discipline applied to a single
statement instead of three).
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from app.ai.providers.base import ProviderLimits, ProviderQuotaExhausted

_WINDOW_KINDS = ("rpm", "tpm", "rpd")


def _window_start(window_kind: str, now: datetime) -> str:
    if window_kind == "rpm" or window_kind == "tpm":
        return now.replace(second=0, microsecond=0).isoformat()
    if window_kind == "rpd":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    raise ValueError(f"unknown window_kind: {window_kind!r}")


def _increments(window_kind: str, tokens: int) -> int:
    return tokens if window_kind == "tpm" else 1


def _limit_for(limits: ProviderLimits, window_kind: str) -> int | None:
    return getattr(limits, window_kind)


async def reserve(
    conn: aiosqlite.Connection, provider_id: str, limits: ProviderLimits, tokens_estimate: int,
    *, now: datetime | None = None,
) -> None:
    """Atomically reserves 1 request + `tokens_estimate` tokens against
    every metered window (rpm/tpm/rpd). Raises `ProviderQuotaExhausted`
    naming the specific window if any would be exceeded — nothing is left
    partially consumed (the router treats this exactly like a live 429
    from the provider itself: try the next one).

    `now` is an injectable clock (defaults to real time) — the only way
    to exercise rolling-window boundary arithmetic deterministically
    (EV-P3-07): a real clock can't be relied on to actually cross a
    minute or day boundary mid-test."""
    now = now or datetime.now(timezone.utc)
    now_str = now.isoformat()
    exceeded_window: str | None = None

    for window_kind in _WINDOW_KINDS:
        limit = _limit_for(limits, window_kind)
        if limit is None:
            continue  # unmetered (Ollama) — nothing to reserve against
        window_start = _window_start(window_kind, now)
        await conn.execute(
            """INSERT INTO quota_ledger (provider, window_kind, window_start, used, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)
               ON CONFLICT (provider, window_kind, window_start) DO NOTHING""",
            (provider_id, window_kind, window_start, now_str, now_str),
        )
        incr = _increments(window_kind, tokens_estimate)
        cur = await conn.execute(
            """UPDATE quota_ledger SET used = used + ?, updated_at = ?
               WHERE provider = ? AND window_kind = ? AND window_start = ? AND used + ? <= ?
               RETURNING used""",
            (incr, now_str, provider_id, window_kind, window_start, incr, limit),
        )
        row = await cur.fetchone()
        if row is None:
            exceeded_window = window_kind
            break

    if exceeded_window is not None:
        await conn.rollback()
        raise ProviderQuotaExhausted(f"{provider_id}: {exceeded_window} window exhausted")
    await conn.commit()


async def record_actual(
    conn: aiosqlite.Connection, provider_id: str, tokens_estimate: int, tokens_actual: int | None,
    *, now: datetime | None = None,
) -> None:
    """True-up the TPM window to what the provider actually reported, so
    the ledger's numbers match the provider's own (Phase 3 gate) rather
    than drifting from the pre-call estimate. A `None` actual (a provider
    that doesn't report usage) leaves the estimate as the final number —
    still a reservation, just not correctable. Never raises: a window
    that rolled over between reserve and this call just means the delta
    applies to a now-irrelevant row, which is harmless."""
    if tokens_actual is None or tokens_actual == tokens_estimate:
        return
    delta = tokens_actual - tokens_estimate
    now = now or datetime.now(timezone.utc)
    window_start = _window_start("tpm", now)
    await conn.execute(
        """UPDATE quota_ledger SET used = MAX(0, used + ?), updated_at = ?
           WHERE provider = ? AND window_kind = 'tpm' AND window_start = ?""",
        (delta, now.isoformat(), provider_id, window_start),
    )
    await conn.commit()


async def remaining(
    conn: aiosqlite.Connection, provider_id: str, limits: ProviderLimits, *, now: datetime | None = None
) -> dict:
    """Current-window usage and remaining budget per window kind — what
    `GET /quota` reports so a long run doesn't die halfway through
    unexplained (A§7.3)."""
    now = now or datetime.now(timezone.utc)
    result: dict[str, dict] = {}
    for window_kind in _WINDOW_KINDS:
        limit = _limit_for(limits, window_kind)
        if limit is None:
            result[window_kind] = {"used": 0, "limit": None, "remaining": None}
            continue
        window_start = _window_start(window_kind, now)
        cur = await conn.execute(
            "SELECT used FROM quota_ledger WHERE provider = ? AND window_kind = ? AND window_start = ?",
            (provider_id, window_kind, window_start),
        )
        row = await cur.fetchone()
        used = row["used"] if row else 0
        result[window_kind] = {"used": used, "limit": limit, "remaining": max(0, limit - used)}
    return result
