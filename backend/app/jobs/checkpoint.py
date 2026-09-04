"""Cursor persistence (A§10.3). Written after each successful page, so a
crash at link 40 resumes at link 40's last page, not link 1 and not link
40's start again.
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


async def save_checkpoint(conn: aiosqlite.Connection, job_id: str, link_id: str, cursor: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        """INSERT INTO checkpoints (job_id, link_id, cursor, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET cursor = excluded.cursor, updated_at = excluded.updated_at""",
        (job_id, link_id, cursor, now),
    )
    # A checkpoint is proof of life: without touching the heartbeat here,
    # the stale-claim reaper (jobs/claim.py) can reclaim a job that is
    # actively making progress but simply takes longer than
    # `stale_claim_seconds` to finish a single run() call, causing the
    # same job to be double-claimed and processed concurrently.
    await conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (now, job_id))
    await conn.commit()


async def load_checkpoint(conn: aiosqlite.Connection, job_id: str) -> str | None:
    cur = await conn.execute("SELECT cursor FROM checkpoints WHERE job_id = ?", (job_id,))
    row = await cur.fetchone()
    return row["cursor"] if row else None
