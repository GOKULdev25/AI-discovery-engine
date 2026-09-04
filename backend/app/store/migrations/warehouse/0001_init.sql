-- Per-project warehouse.duckdb (A§9). Single-writer committer only — no
-- other write path exists in the codebase (IP rule 2 🔒, EV-INV-02).
--
-- The `documents` schema is fixed here per A§8 and does not change again.
-- Q&A (doc_type qa_question/qa_answer, parent_id self-link) ships in P7
-- with zero migration to this table.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id              VARCHAR PRIMARY KEY,
    project_id          VARCHAR NOT NULL,
    batch_id            VARCHAR NOT NULL,
    source              VARCHAR NOT NULL,   -- youtube | reddit | appstore | playstore | flipkart | amazon | llm_dom | fixture
    doc_type            VARCHAR NOT NULL,   -- review | comment | post | qa_question | qa_answer
    source_url          VARCHAR NOT NULL,
    subject             VARCHAR,            -- e.g. product/video/thread title
    product_id          VARCHAR,
    variant             VARCHAR,            -- country/locale/app-variant this row was collected under
    captured_at         TIMESTAMP NOT NULL, -- when WE captured it — always set
    authored_at         TIMESTAMP,          -- nullable, stays null (P§6 "nothing fabricated")
    author_hash         VARCHAR,            -- sha256(author_id); raw handle never lands here
    text                VARCHAR,
    lang                VARCHAR,
    rating              DOUBLE,             -- nullable, stays null
    verified_purchase   BOOLEAN,            -- nullable, stays null
    engagement          VARCHAR,            -- JSON-encoded (likes/upvotes/replies), source-dependent
    parent_id           VARCHAR,            -- self-link for qa_answer -> qa_question
    lane                VARCHAR NOT NULL,   -- api | browser | llm_dom — provenance, never optional
    extractor_version   VARCHAR NOT NULL,
    raw                 VARCHAR NOT NULL    -- JSON-encoded original payload — the escape hatch
);

CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_batch ON documents(batch_id);
CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_id);

CREATE TABLE IF NOT EXISTS embeddings (
    doc_id      VARCHAR PRIMARY KEY,
    model       VARCHAR NOT NULL,
    -- Packed float32 bytes (struct.pack), not FLOAT[384]: a native
    -- fixed-size array column measured at ~150x slower per row for this
    -- exact shape on this platform (0.7s/row vs ~4ms/row for BLOB) even
    -- via parameter binding, not just inline literals — a DuckDB
    -- array/list-handling issue, not a memory_limit tuning problem
    -- (Docs/FEASIBILITY_LOG.md, 2026-08-29). `dim` records the vector
    -- length so a reader can `struct.unpack(f"{dim}f", vector)` without
    -- hardcoding 384 elsewhere.
    vector      BLOB,
    dim         INTEGER,
    created_at  TIMESTAMP NOT NULL
);

INSERT INTO schema_version (version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
