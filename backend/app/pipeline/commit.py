"""The commit path 🔒 (A§9, IP§2.3). Workers stage normalized rows into
`ops.sqlite`'s `staging_docs`; this is the single drain that moves them
into `warehouse.duckdb` through the project's one `Committer` (A§9's
single-writer rule). Getting this wrong is the most likely way to
corrupt the warehouse, so it is a design rule with a crash test
(EV-P2-09), not an implementation detail.

Crash safety is structural, not incidental: a `staging_docs` row is only
marked `committed = 1` *after* `Committer.commit_rows()` has returned
successfully. A crash between those two steps leaves the row `committed
= 0`, so the next drain re-sends it — safe because `commit_rows` is
idempotent on `doc_id` (`ON CONFLICT DO NOTHING`), not because the crash
window happens to be narrow.
"""

from __future__ import annotations

import json

import aiosqlite

from app.store.duckdb import Committer

DRAIN_BATCH_SIZE = 500


async def drain_staging(ops_conn: aiosqlite.Connection, committer: Committer) -> int:
    """Drains every currently-staged, uncommitted row for this project
    into the warehouse. Returns the number of rows drained."""
    total = 0
    while True:
        cur = await ops_conn.execute(
            "SELECT id, row_json FROM staging_docs WHERE committed = 0 ORDER BY id LIMIT ?",
            (DRAIN_BATCH_SIZE,),
        )
        rows = await cur.fetchall()
        if not rows:
            return total
        docs = [json.loads(r["row_json"]) for r in rows]
        await committer.commit_rows(docs)
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        await ops_conn.execute(
            f"UPDATE staging_docs SET committed = 1 WHERE id IN ({placeholders})", ids
        )
        await ops_conn.commit()
        total += len(rows)
        if len(rows) < DRAIN_BATCH_SIZE:
            return total
