-- App-level data/app.sqlite (A§7.3): global on purpose. The quota ledger
-- belongs to the key, not the study; the LLM cache is keyed on content hash
-- across all projects.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,            -- gemini | groq | ollama
    window_kind TEXT NOT NULL,         -- rpm | tpm | rpd
    window_start TEXT NOT NULL,        -- ISO8601, floored to the window
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quota_window
    ON quota_ledger(provider, window_kind, window_start);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,        -- sha256(content_hash + prompt_version)
    response_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO schema_version (version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
