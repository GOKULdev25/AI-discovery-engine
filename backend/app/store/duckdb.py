"""DuckDB warehouse access (A§9). This is the ONLY module in the codebase
that may call `duckdb.connect(...)` in read/write mode (IP rule 2 🔒;
EV-INV-02 greps for this). Workers never write here directly — they stage
normalized rows into `ops.sqlite`'s `staging_docs`, and the per-project
`Committer` below is the single writer that drains staging into
`warehouse.duckdb`. Read paths (analytics, chat, export) use
`open_read_only`, which every other module must go through instead of
calling `duckdb.connect` itself.
"""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import duckdb

_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "warehouse"

_DOC_COLUMNS = [
    "doc_id", "project_id", "batch_id", "source", "doc_type", "source_url",
    "subject", "product_id", "variant", "captured_at", "authored_at",
    "author_hash", "text", "lang", "rating", "verified_purchase",
    "engagement", "parent_id", "lane", "extractor_version", "raw",
]


def _apply_migrations_sync(conn: duckdb.DuckDBPyConnection) -> None:
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row[0] if row else 0
    except duckdb.CatalogException:
        current = 0

    applied: list[int] = []
    for f in files:
        version = int(f.stem.split("_", 1)[0])
        if version <= current:
            continue
        sql = f.read_text(encoding="utf-8")
        for statement in _split_statements(sql):
            conn.execute(statement)
        conn.execute("UPDATE schema_version SET version = ?", [version])
        applied.append(version)

    if 3 in applied:
        # Documents enriched before 0003 have an `enrichment` row already,
        # and `enrich_pending_documents` only looks at rows that have none —
        # so without this the entire pre-existing corpus keeps a null
        # engagement forever. Runs exactly once, as part of the migration
        # that introduced the columns, rather than as a scan on every drain.
        _backfill_engagement_sync(conn)


def _backfill_engagement_sync(conn: duckdb.DuckDBPyConnection) -> None:
    """Fills `engagement_count`/`engagement_kind` from each document's raw
    `engagement` blob, using the per-source mapping declared in
    `app/sources/profiles.py`. Deliberately not expressed as SQL: the
    key to read differs per source, and duplicating that mapping in a
    migration would give it a second home that could drift from the
    profiles module."""
    from app.pipeline.enrich import normalize_engagement

    rows = conn.execute(
        """SELECT d.doc_id, d.source, d.engagement FROM documents d
           JOIN enrichment e ON d.doc_id = e.doc_id
           WHERE d.engagement IS NOT NULL"""
    ).fetchall()
    updates = []
    for doc_id, source, raw in rows:
        count, kind = normalize_engagement(source, raw)
        if kind is not None:
            updates.append((doc_id, count, kind))
    if not updates:
        return
    for i in range(0, len(updates), 500):
        chunk = updates[i : i + 500]
        count_cases = " ".join(
            f"WHEN {_sql_literal(d)} THEN {_sql_literal(c)}" for d, c, _k in chunk
        )
        kind_cases = " ".join(
            f"WHEN {_sql_literal(d)} THEN {_sql_literal(k)}" for d, _c, k in chunk
        )
        ids = ",".join(_sql_literal(d) for d, _c, _k in chunk)
        conn.execute(
            f"""UPDATE enrichment SET
                engagement_count = CASE doc_id {count_cases} END,
                engagement_kind = CASE doc_id {kind_cases} END
                WHERE doc_id IN ({ids})"""
        )


def _configure_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB's default `memory_limit` is ~80% of *total* system RAM,
    which on a machine under real memory pressure (observed: ~1GB free
    out of 16GB total) causes allocation failures on trivially small
    queries. This project's per-document analytical workload does not
    need gigabytes; capping it low avoids competing with whatever else
    is running on the operator's machine."""
    conn.execute("PRAGMA memory_limit='1GB'")


def unpack_embedding(blob: bytes, dim: int) -> list[float]:
    """The inverse of `Committer.insert_embeddings`'s packing — every
    reader of the `embeddings` table (Phase 5's retrieval) goes through
    this rather than re-implementing struct.unpack with a hardcoded
    width."""
    return list(struct.unpack(f"{dim}f", blob))


def _sql_literal(value: object) -> str:
    """Formats a Python value as a DuckDB SQL literal, standard-SQL-quoted
    (single quotes doubled) for strings. Used instead of `?` parameter
    binding for bulk inserts — see `_commit_rows_sync`. Every value in a
    row must go through this; there is no other path that touches the SQL
    text directly."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_sql_literal(v) for v in value) + "]"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _split_statements(script: str) -> list[str]:
    # Strip `--` line comments first (our DDL never puts `--` inside a
    # string literal), then split on `;`. Splitting on the raw script would
    # break on a semicolon that happens to fall inside a comment.
    stripped_lines = []
    for line in script.splitlines():
        idx = line.find("--")
        stripped_lines.append(line[:idx] if idx != -1 else line)
    stripped = "\n".join(stripped_lines)
    return [s.strip() for s in stripped.split(";") if s.strip()]


class Committer:
    """The single writer for one project's warehouse.duckdb. One instance
    per project per process — see `get_committer`."""

    def __init__(self, project_dir: Path):
        self._path = project_dir / "warehouse.duckdb"
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._conn is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await asyncio.to_thread(self._open_sync)

    def _open_sync(self) -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(str(self._path))
        _configure_connection(conn)
        _apply_migrations_sync(conn)
        return conn

    async def commit_rows(self, rows: list[dict]) -> int:
        """Insert already-normalized A§8 rows. Idempotent on doc_id
        (ON CONFLICT DO NOTHING) — Phase 2 owns the real dedup logic ahead
        of this call; this is the durability floor underneath it."""
        if not rows:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._commit_rows_sync, rows)

    def _commit_rows_sync(self, rows: list[dict]) -> int:
        assert self._conn is not None
        # Inlined, escaped literals instead of `?` parameter binding —
        # measured on this platform, parameter binding costs ~6-7ms per
        # bound value (not per row), which turns a 500-row drain into
        # multiple seconds for no reason; literal VALUES for the same
        # data lands in low tens of milliseconds. See `_sql_literal` for
        # the escaping that keeps this safe.
        values = [self._row_to_values(row) for row in rows]
        rows_sql = ",".join(
            "(" + ",".join(_sql_literal(v) for v in row) + ")" for row in values
        )
        sql = (
            f"INSERT INTO documents ({', '.join(_DOC_COLUMNS)}) "
            f"VALUES {rows_sql} "
            f"ON CONFLICT (doc_id) DO NOTHING"
        )
        self._conn.execute(sql)
        return len(values)

    @staticmethod
    def _row_to_values(row: dict) -> list:
        # `engagement` and `raw` arrive as Python objects (dict/list/None)
        # per the A§8 row contract and are JSON-encoded once, here.
        values = []
        for col in _DOC_COLUMNS:
            value = row.get(col)
            if col in ("engagement", "raw") and value is not None:
                value = json.dumps(value)
            values.append(value)
        return values

    async def update_lang(self, updates: list[tuple[str, str]]) -> int:
        """`updates` is [(doc_id, lang), ...]. `lang` is the one A§8 column
        enrichment writes into directly — everything else derived lives in
        the `enrichment` table so `documents` never needs a new column."""
        if not updates:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._update_lang_sync, updates)

    def _update_lang_sync(self, updates: list[tuple[str, str]]) -> int:
        assert self._conn is not None
        cases = " ".join(
            f"WHEN {_sql_literal(doc_id)} THEN {_sql_literal(lang)}" for doc_id, lang in updates
        )
        doc_ids = ",".join(_sql_literal(doc_id) for doc_id, _ in updates)
        self._conn.execute(
            f"UPDATE documents SET lang = CASE doc_id {cases} END WHERE doc_id IN ({doc_ids})"
        )
        return len(updates)

    async def upsert_enrichment(self, rows: list[dict]) -> int:
        """`rows`: dicts with `doc_id` and any of lang_confidence,
        sentiment_prior, simhash, gate_band, gate_score,
        engagement_count, engagement_kind. Re-running enrichment on the
        same doc updates in place (this is derived data, not a source
        fact — idempotent overwrite is correct here, unlike
        `documents`)."""
        if not rows:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._upsert_enrichment_sync, rows)

    def _upsert_enrichment_sync(self, rows: list[dict]) -> int:
        assert self._conn is not None
        cols = [
            "doc_id",
            "lang_confidence",
            "sentiment_prior",
            "simhash",
            "gate_band",
            "gate_score",
            "engagement_count",
            "engagement_kind",
            "enriched_at",
        ]
        now = datetime.now(timezone.utc).isoformat()
        values_sql = ",".join(
            "(" + ",".join(_sql_literal(row.get(c) if c != "enriched_at" else now) for c in cols) + ")"
            for row in rows
        )
        update_cols = [c for c in cols if c not in ("doc_id",)]
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
        self._conn.execute(
            f"INSERT INTO enrichment ({', '.join(cols)}) VALUES {values_sql} "
            f"ON CONFLICT (doc_id) DO UPDATE SET {set_clause}"
        )
        return len(rows)

    async def update_gate_band(self, updates: list[tuple[str, str, float | None]]) -> int:
        """`updates` is [(doc_id, gate_band, gate_score), ...] — Phase 3's
        LLM classification resolving the embedding gate's "ambiguous" band
        (IP§3.2). A targeted partial UPDATE, not `upsert_enrichment()`:
        that call always rewrites every derived column from what's in its
        `rows` dicts, so reusing it here with only gate_band/gate_score
        would silently null out lang_confidence/sentiment_prior/simhash
        for rows Phase 2 had already enriched."""
        if not updates:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._update_gate_band_sync, updates)

    def _update_gate_band_sync(self, updates: list[tuple[str, str, float | None]]) -> int:
        assert self._conn is not None
        band_cases = " ".join(
            f"WHEN {_sql_literal(doc_id)} THEN {_sql_literal(band)}" for doc_id, band, _score in updates
        )
        score_cases = " ".join(
            f"WHEN {_sql_literal(doc_id)} THEN {_sql_literal(score)}" for doc_id, _band, score in updates
        )
        doc_ids = ",".join(_sql_literal(doc_id) for doc_id, _band, _score in updates)
        self._conn.execute(
            f"""UPDATE enrichment SET
                gate_band = CASE doc_id {band_cases} END,
                gate_score = CASE doc_id {score_cases} END
                WHERE doc_id IN ({doc_ids})"""
        )
        return len(updates)

    async def insert_embeddings(self, rows: list[dict]) -> int:
        """`rows`: dicts with doc_id, model, vector (list[float])."""
        if not rows:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._insert_embeddings_sync, rows)

    def _insert_embeddings_sync(self, rows: list[dict]) -> int:
        # BLOB + `?` parameter binding, not a native FLOAT[] array column:
        # measured at ~150x slower per row for a 384-wide array on this
        # platform regardless of literal-vs-parameter (0.7s/row either
        # way) — see the `embeddings` migration's comment and
        # Docs/FEASIBILITY_LOG.md, 2026-08-29.
        assert self._conn is not None
        now = datetime.now(timezone.utc).isoformat()
        params = []
        for row in rows:
            vector = row["vector"]
            packed = struct.pack(f"{len(vector)}f", *vector)
            params.append([row["doc_id"], row["model"], packed, len(vector), now])
        self._conn.executemany(
            "INSERT INTO embeddings (doc_id, model, vector, dim, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (doc_id) DO NOTHING",
            params,
        )
        return len(rows)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A read connection sharing this committer's in-process database
        instance. DuckDB refuses two independent `connect()` calls against
        the same file with different read_only settings from one process,
        so every in-process reader (analytics, chat, export) must go
        through this rather than opening its own connection."""
        assert self._conn is not None
        return self._conn.cursor()


_committers: dict[Path, Committer] = {}
_committers_lock = asyncio.Lock()


async def ensure_migrated(project_dir: Path) -> None:
    """Applies migrations to warehouse.duckdb without joining the
    process-wide committer registry, and closes the connection again —
    used by project scaffolding, which needs the file to exist with a
    fresh schema, not a live connection sitting open (which would leave a
    stray `warehouse.duckdb.wal` at rest, breaking the A§7.1 tree check)."""
    def _open_migrate_close() -> None:
        conn = duckdb.connect(str(project_dir / "warehouse.duckdb"))
        try:
            _configure_connection(conn)
            _apply_migrations_sync(conn)
        finally:
            conn.close()

    project_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_open_migrate_close)


async def get_committer(project_dir: Path) -> Committer:
    """Returns the process-wide singleton Committer for this project,
    creating and starting it on first use. This is what makes 'no other
    write path exists' true structurally rather than by convention."""
    project_dir = project_dir.resolve()
    async with _committers_lock:
        committer = _committers.get(project_dir)
        if committer is None:
            committer = Committer(project_dir)
            await committer.start()
            _committers[project_dir] = committer
        return committer


async def forget_committer(project_dir: Path) -> None:
    """Closes and drops this project's committer — used right before its
    directory is deleted (IP§0.2), so no process holds a handle into a
    directory that no longer exists."""
    project_dir = project_dir.resolve()
    async with _committers_lock:
        committer = _committers.pop(project_dir, None)
    if committer is not None:
        await committer.close()


async def close_all() -> None:
    async with _committers_lock:
        for committer in _committers.values():
            await committer.close()
        _committers.clear()


async def get_reader(project_dir: Path) -> duckdb.DuckDBPyConnection:
    """The in-process read path for analytics, chat, and export (Phase 4/5).
    Ensures the project's committer exists, then hands back a cursor onto
    its live connection — see `Committer.cursor`."""
    committer = await get_committer(project_dir)
    return committer.cursor()


def open_read_only(project_dir: Path) -> duckdb.DuckDBPyConnection:
    """Read path for a separate process with no live committer of its own —
    an offline eval script or a maintenance CLI run after the API has
    shut down. Never used for writes, and never used from within the API
    process (use `get_reader` there — see the docstring above)."""
    path = project_dir / "warehouse.duckdb"
    conn = duckdb.connect(str(path), read_only=True)
    _configure_connection(conn)
    return conn
