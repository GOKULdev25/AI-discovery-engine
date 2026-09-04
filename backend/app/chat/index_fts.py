"""Keeps `ops.sqlite`'s `documents_fts` (BM25 half of Phase 5's hybrid
retrieval, A§12) synced from `warehouse.duckdb`. Piggybacks on
`enrichment.enriched_at` as a high-water mark rather than tracking a
second per-doc "have I synced this" set — enrichment already timestamps
every document exactly once (Phase 2), so this only ever asks for
documents enriched after the last sync.
"""

from __future__ import annotations

import aiosqlite
import duckdb

_EPOCH = "1970-01-01T00:00:00+00:00"


async def sync_fts_index(ops_conn: aiosqlite.Connection, reader: duckdb.DuckDBPyConnection) -> int:
    cur = await ops_conn.execute("SELECT value FROM fts_sync_state WHERE key = 'last_synced_at'")
    row = await cur.fetchone()
    last_synced = row["value"] if row else _EPOCH

    rows = reader.execute(
        """SELECT d.doc_id, d.batch_id, d.text, e.enriched_at
           FROM documents d JOIN enrichment e ON d.doc_id = e.doc_id
           WHERE CAST(e.enriched_at AS VARCHAR) > ?
           ORDER BY e.enriched_at""",
        [last_synced],
    ).fetchall()
    if not rows:
        return 0

    for doc_id, batch_id, text, _enriched_at in rows:
        await ops_conn.execute(
            "INSERT INTO documents_fts (doc_id, batch_id, text) VALUES (?, ?, ?)",
            (doc_id, batch_id, text or ""),
        )
    new_high_water = str(rows[-1][3])
    await ops_conn.execute(
        """INSERT INTO fts_sync_state (key, value) VALUES ('last_synced_at', ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (new_high_water,),
    )
    await ops_conn.commit()
    return len(rows)


async def bm25_search(
    ops_conn: aiosqlite.Connection, query: str, *, batch_id: str | None = None, limit: int = 30
) -> list[tuple[str, float]]:
    """Returns [(doc_id, bm25_score), ...] best-first. FTS5's `bm25()`
    returns *lower is better* (it's a cost, not a similarity) — negated
    here so every caller in this codebase can treat "higher is better"
    uniformly, matching cosine similarity's convention."""
    sql = "SELECT doc_id, bm25(documents_fts) AS score FROM documents_fts WHERE documents_fts MATCH ?"
    params: list[object] = [query]
    if batch_id:
        sql += " AND batch_id = ?"
        params.append(batch_id)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    try:
        cur = await ops_conn.execute(sql, params)
        rows = await cur.fetchall()
    except aiosqlite.OperationalError:
        # FTS5's query syntax rejects some inputs outright (bare
        # punctuation, an unbalanced quote) — a bad query is "no lexical
        # matches", not a crash of the whole retrieval call.
        return []
    return [(r["doc_id"], -r["score"]) for r in rows]
