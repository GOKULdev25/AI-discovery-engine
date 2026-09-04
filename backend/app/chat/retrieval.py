"""Hybrid retrieval (A§12, IP§5): BM25 via SQLite FTS5 for lexical
precision, plus vector search over `fastembed` embeddings for semantic
recall, merged by reciprocal rank fusion (RRF) — a standard, scale-free
way to combine two rankers whose raw scores (a BM25 cost, a cosine
similarity) aren't on comparable scales, so averaging them directly would
be meaningless.

Documents the local gate already decided are `drop` (spam, off-topic)
never enter the candidate set — the same cost/privacy property Phase 3's
classify.py holds for LLM requests applies here: junk the gate already
identified shouldn't come back to life as "evidence."
"""

from __future__ import annotations

import aiosqlite
import duckdb

from app.chat.index_fts import bm25_search
from app.pipeline.enrich_local import embed_texts
from app.pipeline.gate import cosine_similarity
from app.store.duckdb import unpack_embedding

RRF_K = 60


def reciprocal_rank_fusion(*ranked_lists: list[tuple[str, float]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (doc_id, _score) in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])


async def vector_search(
    reader: duckdb.DuckDBPyConnection,
    query_vector: list[float],
    *,
    batch_id: str | None = None,
    source: str | None = None,
    limit: int = 30,
) -> list[tuple[str, float]]:
    clause = "d.batch_id = ?" if batch_id else "1 = 1"
    params: list[object] = [batch_id] if batch_id else []
    if source:
        clause += " AND d.source = ?"
        params.append(source)
    rows = reader.execute(
        f"""SELECT d.doc_id, em.vector, em.dim FROM documents d
            JOIN embeddings em ON d.doc_id = em.doc_id
            LEFT JOIN enrichment e ON d.doc_id = e.doc_id
            WHERE {clause} AND (e.gate_band IS NULL OR e.gate_band != 'drop')""",
        params,
    ).fetchall()
    scored = [(doc_id, cosine_similarity(query_vector, unpack_embedding(blob, dim))) for doc_id, blob, dim in rows]
    scored.sort(key=lambda item: -item[1])
    return scored[:limit]


def _fetch_documents(reader: duckdb.DuckDBPyConnection, doc_ids: list[str]) -> dict[str, dict]:
    if not doc_ids:
        return {}
    placeholders = ", ".join("?" for _ in doc_ids)
    rows = reader.execute(
        f"""SELECT doc_id, source, doc_type, source_url, captured_at, rating, text
            FROM documents WHERE doc_id IN ({placeholders})""",
        doc_ids,
    ).fetchall()
    columns = [c[0] for c in reader.description]
    return {row[0]: dict(zip(columns, row)) for row in rows}


async def hybrid_retrieve(
    ops_conn: aiosqlite.Connection,
    reader: duckdb.DuckDBPyConnection,
    query: str,
    *,
    batch_id: str | None = None,
    source: str | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Returns up to `top_k` documents, richest-evidence-first, each a
    dict with doc_id/source/doc_type/source_url/captured_at/rating/text.
    Never raises on "no results" — an empty list is a legitimate answer
    (grounding.py turns that into an explicit decline, never a guess)."""
    query_vectors = await embed_texts([query])
    query_vector = query_vectors[0] if query_vectors else None

    # The FTS5 index carries only (doc_id, batch_id, text), so a source
    # filter cannot be pushed into the lexical half — it is applied after
    # hydration instead. Widen the candidate pool when filtering so the
    # post-filter still has enough left to fill `top_k`.
    fanout = 3 if source is None else 8
    bm25_ranked = await bm25_search(ops_conn, query, batch_id=batch_id, limit=top_k * fanout)
    vector_ranked = (
        await vector_search(
            reader, query_vector, batch_id=batch_id, source=source, limit=top_k * fanout
        )
        if query_vector
        else []
    )
    fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked)
    if source is None:
        fused = fused[:top_k]

    docs_by_id = _fetch_documents(reader, [doc_id for doc_id, _score in fused])
    results = []
    for doc_id, score in fused:
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue  # a race with a delete/retention job elsewhere — skip, don't fabricate
        if source is not None and doc.get("source") != source:
            continue
        doc = dict(doc)
        doc["captured_at"] = str(doc["captured_at"]) if doc["captured_at"] is not None else None
        doc["retrieval_score"] = score
        results.append(doc)
        if len(results) >= top_k:
            break
    return results
