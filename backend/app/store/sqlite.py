"""SQLite (WAL mode) access for ops.sqlite (per-project) and app.sqlite
(global — A§7.3). Plain numbered SQL migrations, no ORM (IP§0.3): the
SQLite -> Postgres door stays open, so no migration here ever uses
`INSERT OR REPLACE` (EV-P0-13).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _apply_migrations(conn: aiosqlite.Connection, kind: str) -> None:
    mig_dir = _MIGRATIONS_DIR / kind
    files = sorted(mig_dir.glob("*.sql"))
    cur = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    has_version_table = await cur.fetchone() is not None
    current = 0
    if has_version_table:
        cur = await conn.execute("SELECT version FROM schema_version")
        row = await cur.fetchone()
        current = row[0] if row else 0

    for f in files:
        version = int(f.stem.split("_", 1)[0])
        if version <= current:
            continue
        sql = f.read_text(encoding="utf-8")
        await conn.executescript(sql)
        await conn.execute("UPDATE schema_version SET version = ?", (version,))
        await conn.commit()


async def open_db(path: Path, kind: str) -> aiosqlite.Connection:
    """Open a WAL-mode SQLite connection at `path`, applying migrations for
    `kind` ('ops' or 'app'). Callers own the connection's lifecycle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    # NORMAL is the documented pairing for WAL mode: still safe from
    # corruption, and avoids an fsync on every single commit. Without it,
    # the job engine's per-document commits (staging, events, checkpoint)
    # are dominated by sync overhead rather than actual work — observed as
    # ~30x slower batch processing on Windows.
    await conn.execute("PRAGMA synchronous=NORMAL")
    await _apply_migrations(conn, kind)
    return conn


async def open_ops_db(project_dir: Path) -> aiosqlite.Connection:
    return await open_db(project_dir / "ops.sqlite", "ops")


async def open_app_db(app_sqlite_path: Path) -> aiosqlite.Connection:
    return await open_db(app_sqlite_path, "app")


@asynccontextmanager
async def app_db(app_sqlite_path: Path):
    """A short-lived app.sqlite connection for one request/call — same
    reasoning as `ops_db()` below: never a shared singleton, since WAL
    mode is built for multiple real connections and the quota ledger
    (A§7.3) needs `BEGIN IMMEDIATE` transactions to serialize concurrent
    reserve attempts, which is only safe per-connection."""
    conn = await open_app_db(app_sqlite_path)
    try:
        yield conn
    finally:
        await conn.close()


@asynccontextmanager
async def ops_db(project_dir: Path):
    """A short-lived ops.sqlite connection for one request/call.

    Deliberately NOT a shared singleton: sqlite3's implicit-transaction
    model means an `execute()` on one cursor can still be "in progress"
    (not yet fully fetched) when another concurrent caller on the *same*
    connection tries to `commit()`, which raises
    'cannot commit transaction - SQL statements in progress'. WAL mode is
    built for multiple real connections instead — the same reasoning
    behind the atomic-claim design (jobs/claim.py) already assumes N
    separate connections, so giving every worker/request its own is the
    consistent choice, not just a workaround.
    """
    conn = await open_ops_db(project_dir)
    try:
        yield conn
    finally:
        await conn.close()
