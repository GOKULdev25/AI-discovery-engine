"""Shared Phase 5 eval scaffolding: seed fully-enriched documents (text,
embeddings, gate_band) directly through the committer — the same
direct-manipulation idiom Phase 3's EV-P3-10 already uses — and sync them
into `documents_fts` so both halves of hybrid retrieval actually work in
a test, not just the pipeline that normally populates them live.
"""

from __future__ import annotations

from app.chat.index_fts import sync_fts_index
from app.pipeline import enrich_local

_NOW = "2026-08-29T00:00:00Z"


def doc_row(
    doc_id: str, project_id: str, text: str, *, source: str = "playstore", batch_id: str = "b", captured_at: str = _NOW
) -> dict:
    return {
        "doc_id": doc_id, "project_id": project_id, "batch_id": batch_id, "source": source,
        "doc_type": "review", "source_url": f"fixture://{doc_id}", "captured_at": captured_at,
        "lane": "api", "extractor_version": "v", "raw": {}, "text": text,
    }


async def seed_and_index(committer, ops_conn, rows: list[dict], *, gate_band: str = "keep") -> None:
    """`rows`: from `doc_row()`. Commits, enriches (real fastembed
    embeddings — retrieval needs real vectors, not stubs), gate-bands
    everything the same way (default "keep" so it's retrievable), and
    syncs the result into `documents_fts`."""
    await committer.commit_rows(rows)

    doc_dicts = [{"doc_id": r["doc_id"], "text": r["text"]} for r in rows]
    enriched = await enrich_local.enrich_documents(doc_dicts)

    await committer.upsert_enrichment([
        {
            "doc_id": e["doc_id"], "lang_confidence": e["lang_confidence"],
            "sentiment_prior": e["sentiment_prior"], "simhash": e["simhash"],
            "gate_band": gate_band, "gate_score": 1.0,
        }
        for e in enriched
    ])
    await committer.insert_embeddings([
        {"doc_id": e["doc_id"], "model": enrich_local.EMBEDDING_MODEL, "vector": e["vector"]}
        for e in enriched if e["vector"] is not None
    ])

    reader = committer.cursor()
    await sync_fts_index(ops_conn, reader)
