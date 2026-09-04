-- Phase 2 local enrichment (A§11.2). `documents` is frozen per A§8 — this
-- table holds everything *derived* about a document (never anything a
-- source provided), so enrichment/classification never has to touch the
-- frozen schema. `lang` is the one exception: it's already an A§8 column
-- and gets UPDATEd in place once detected.

CREATE TABLE IF NOT EXISTS enrichment (
    doc_id              VARCHAR PRIMARY KEY,
    lang_confidence     DOUBLE,             -- confidence of the language-detection guess
    sentiment_prior     DOUBLE,             -- VADER-class lexicon score, NEVER the final label (P§6)
    simhash             VARCHAR,            -- near-duplicate fingerprint (hex) — a flag, never a delete (IP§2.2)
    gate_band           VARCHAR,            -- keep | drop | ambiguous (A§11.2 three-stage gate)
    gate_score          DOUBLE,             -- embedding-similarity score that produced gate_band
    enriched_at         TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_enrichment_band ON enrichment(gate_band);

-- schema_version is bumped by the migration runner itself after this file
-- applies (see store/duckdb.py::_apply_migrations_sync) — 0001's bootstrap
-- INSERT is the only migration that touches this table directly.
