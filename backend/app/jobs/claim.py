"""DB-claimed work — IP rule 1 🔒. One statement claims exactly one job,
correct under concurrent connections (today: several asyncio workers each
with their own SQLite connection; unchanged tomorrow: N processes against
Postgres). Never an `asyncio.Queue` (EV-INV-01).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

_CLAIM_SQL = """
UPDATE jobs
SET status = 'running', worker_id = ?, claimed_at = ?, heartbeat_at = ?,
    attempts = attempts + 1, updated_at = ?
WHERE id = (
    SELECT id FROM jobs WHERE status = 'pending'
      AND (not_before IS NULL OR not_before <= ?)
    ORDER BY created_at LIMIT 1
)
RETURNING *
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def claim_next_job(conn: aiosqlite.Connection, worker_id: str) -> dict[str, Any] | None:
    now = _now()
    cur = await conn.execute(_CLAIM_SQL, (worker_id, now, now, now, now))
    row = await cur.fetchone()
    await conn.commit()
    if row is None:
        return None
    job = dict(row)
    job["job_spec"] = json.loads(job["job_spec"])
    return job


async def heartbeat(conn: aiosqlite.Connection, job_id: str) -> None:
    await conn.execute(
        "UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (_now(), job_id)
    )
    await conn.commit()


async def mark_done(conn: aiosqlite.Connection, job_id: str) -> None:
    await conn.execute(
        "UPDATE jobs SET status = 'done', updated_at = ? WHERE id = ?",
        (_now(), job_id),
    )
    await conn.commit()


async def mark_failed(
    conn: aiosqlite.Connection, job_id: str, failure_code: str, retryable: bool, attempts: int = 0,
    *, max_attempts: int = 5, backoff_base_seconds: float = 1.0, backoff_max_seconds: float = 60.0,
) -> None:
    now = _now()
    if retryable and attempts < max_attempts:
        # Backoff and requeue (A§8.1) — exponential, capped. The job
        # returns to 'pending' but isn't claimable again until `not_before`.
        backoff_s = min(backoff_base_seconds * (2 ** attempts), backoff_max_seconds)
        not_before = (datetime.now(timezone.utc) + timedelta(seconds=backoff_s)).isoformat()
        await conn.execute(
            """UPDATE jobs SET status = 'pending', worker_id = NULL, claimed_at = NULL,
               not_before = ?, failure_code = ?, retryable = 1, updated_at = ?
               WHERE id = ?""",
            (not_before, failure_code, now, job_id),
        )
    else:
        # Either non-retryable, or a retryable failure that exhausted its
        # attempt budget within this run. `retryable` on the terminal row
        # still reflects the failure's category, so an explicit POST
        # /retry can try it again later even though the automatic loop
        # has stopped.
        await conn.execute(
            """UPDATE jobs SET status = 'failed', failure_code = ?, retryable = ?,
               updated_at = ? WHERE id = ?""",
            (failure_code, int(retryable), now, job_id),
        )
    await conn.commit()


async def reap_stale_claims(conn: aiosqlite.Connection, stale_seconds: int) -> int:
    """A `running` job with no heartbeat past `stale_seconds` returns to
    `pending` (IP§0.4). Without this, one crashed worker strands work
    forever.

    Compares against a "now" computed here in Python — the same clock
    source `heartbeat_at` was written from — rather than SQLite's own
    `julianday('now')`. The two clocks aren't perfectly synchronized
    (observed small negative "elapsed" values comparing a Python
    timestamp against SQLite's own now()), which made `stale_seconds=0`
    flaky by design, not just at some unlucky boundary.
    """
    now = _now()
    cur = await conn.execute(
        """UPDATE jobs SET status = 'pending', worker_id = NULL, claimed_at = NULL
           WHERE status = 'running'
             AND heartbeat_at IS NOT NULL
             AND (julianday(?) - julianday(heartbeat_at)) * 86400.0 >= ?
           RETURNING id""",
        (now, stale_seconds),
    )
    rows = await cur.fetchall()
    await conn.commit()
    return len(rows)


async def enqueue_job(
    conn: aiosqlite.Connection,
    *,
    job_id: str,
    project_id: str,
    batch_id: str,
    link_id: str,
    connector_id: str,
    source: str,
    job_spec: dict[str, Any],
) -> None:
    now = _now()
    await conn.execute(
        """INSERT INTO jobs (id, project_id, batch_id, link_id, connector_id,
           source, job_spec, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (job_id, project_id, batch_id, link_id, connector_id, source,
         json.dumps(job_spec), now, now),
    )
    await conn.commit()
