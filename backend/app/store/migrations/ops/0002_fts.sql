-- Lexical half of Phase 5's hybrid retrieval (A§12, IP§5): BM25 via
-- SQLite FTS5. Lives in ops.sqlite, not warehouse.duckdb — DuckDB has no
-- FTS5, and this table is a synced *copy* of document text
-- (chat/index_fts.py keeps it current), not a second source of truth.
-- Because it lives inside this project's own ops.sqlite, cross-project
-- leakage is impossible by construction (A§7.2), not an application-level
-- filter someone could forget (EV-P5-09).
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    doc_id UNINDEXED,
    batch_id UNINDEXED,
    text
);

-- A high-water mark (the max `enrichment.enriched_at` seen so far), not a
-- per-doc marker table: enrichment already timestamps every document
-- exactly once, so this piggybacks on data that already exists instead
-- of tracking a second "have I synced this doc_id" set.
CREATE TABLE IF NOT EXISTS fts_sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- schema_version is bumped by the migration runner itself after this file
-- applies (store/sqlite.py::_apply_migrations) — 0001's bootstrap INSERT
-- is the only migration that touches this table directly.
