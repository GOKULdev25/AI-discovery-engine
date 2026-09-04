-- Per-project ops.sqlite (A§9). Plain numbered SQL, no ORM migration tool
-- (IP§0.3: the SQLite→Postgres door stays open — no INSERT OR REPLACE anywhere).

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,              -- pending | running | done | failed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    link_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    url TEXT NOT NULL,
    connector_id TEXT,                 -- null until classified
    status TEXT NOT NULL,              -- pending | classified | running | done | failed
    failure_code TEXT,                 -- one of the A§8.1 taxonomy codes, or null
    retryable INTEGER,                 -- 0/1, null until a failure is recorded
    doc_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);

CREATE INDEX IF NOT EXISTS idx_links_batch ON links(batch_id);

-- Jobs are the unit of claimable work (IP rule 1 🔒). One job per link per
-- attempt/page-range; expand() may enqueue additional child jobs.
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    link_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    source TEXT NOT NULL,              -- youtube | reddit | appstore | playstore | browser | llm_dom | fixture
    job_spec TEXT NOT NULL,            -- JSON-encoded JobSpec
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    worker_id TEXT,
    claimed_at TEXT,
    heartbeat_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    not_before TEXT,                   -- backoff floor; NULL = claimable now
    failure_code TEXT,
    retryable INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- The 🔒 claim statement (jobs/claim.py) selects on (status, created_at);
-- this index is what keeps that atomic UPDATE cheap under concurrency.
CREATE INDEX IF NOT EXISTS idx_jobs_claimable ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_link ON jobs(link_id);
CREATE INDEX IF NOT EXISTS idx_jobs_heartbeat ON jobs(status, heartbeat_at);

CREATE TABLE IF NOT EXISTS checkpoints (
    job_id TEXT PRIMARY KEY,
    link_id TEXT NOT NULL,
    cursor TEXT,                       -- continuation token / page number / country code
    updated_at TEXT NOT NULL
);

-- SSE durable backing (IP§0.6, EV-P0-08): every emitted event is written here
-- first, so a dropped stream can replay from the last event id it saw.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,             -- JSON
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_batch ON events(batch_id, id);

-- Workers stage normalized rows here; a single committer (store/duckdb.py)
-- drains this table into warehouse.duckdb in batches (A§9 🔒 — rule 2).
CREATE TABLE IF NOT EXISTS staging_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_json TEXT NOT NULL,            -- the full A§8 row, JSON-encoded
    committed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_staging_uncommitted ON staging_docs(committed, id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    batch_id TEXT,                     -- null = whole-project scope
    role TEXT NOT NULL,                -- user | assistant
    content TEXT NOT NULL,
    citations TEXT,                    -- JSON array of doc_ids, or null
    created_at TEXT NOT NULL
);

INSERT INTO schema_version (version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
