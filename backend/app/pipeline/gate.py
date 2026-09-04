"""The three-stage gate (A§11.2), cheapest first:

1. Lexical prefilter — obvious keeps and drops. Free.
2. Embedding similarity — against the project's hand-written prototype
   sentences in `gate/prototypes.yaml`. Free, unlimited, no network.
3. LLM — the ambiguous middle band only. Stubbed here; lands in Phase 3.

Prototypes are research-question-specific and live with the project
(A§7.2) — loaded fresh per project, never cached across projects.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

# A document within this cosine-similarity margin of both a "keep" and a
# "drop" prototype is ambiguous — genuinely unclear, not a rounding
# artifact. Kept as a named constant so the ambiguous-band budget
# (EV-P2-06: <25% of a project's documents) is tunable in one place.
DECISION_MARGIN = 0.05
MIN_WORDS_FOR_KEEP = 3  # a 1-2 word review carries no signal either way


def load_prototypes(prototypes_path: Path) -> dict[str, list[str]]:
    if not prototypes_path.exists():
        return {"keep": [], "drop": []}
    data = yaml.safe_load(prototypes_path.read_text(encoding="utf-8")) or {}
    return {"keep": data.get("keep") or [], "drop": data.get("drop") or []}


def lexical_prefilter(text: str | None) -> str | None:
    """Returns 'keep', 'drop', or None (defer to stage 2). Free, no
    embeddings involved."""
    if not text or not text.strip():
        return "drop"  # nothing to gate — genuinely empty text
    words = text.split()
    if len(words) < MIN_WORDS_FOR_KEEP:
        return "drop"
    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embedding_similarity_band(
    doc_vector: list[float], keep_vectors: list[list[float]], drop_vectors: list[list[float]]
) -> tuple[str, float]:
    """Returns (band, score) where band is keep/drop/ambiguous and score
    is the best keep-similarity minus best drop-similarity — positive
    leans keep, negative leans drop, near zero is ambiguous."""
    best_keep = max((cosine_similarity(doc_vector, v) for v in keep_vectors), default=0.0)
    best_drop = max((cosine_similarity(doc_vector, v) for v in drop_vectors), default=0.0)
    score = best_keep - best_drop
    if abs(score) <= DECISION_MARGIN:
        return "ambiguous", score
    return ("keep" if score > 0 else "drop"), score


async def gate_documents(
    rows: list[dict], prototypes_path: Path
) -> list[dict]:
    """`rows`: [{"doc_id":..., "text":..., "vector": list[float] | None}, ...]
    (vectors already computed by `enrich_local.enrich_documents`, reused
    here rather than re-embedding). Returns [{"doc_id":..., "gate_band":...,
    "gate_score":...}, ...]. Stage 3 (LLM) is a stub: anything embedding
    similarity leaves ambiguous stays ambiguous — Phase 3 classifies it.
    """
    from app.pipeline.enrich_local import embed_texts

    prototypes = load_prototypes(prototypes_path)
    keep_sentences, drop_sentences = prototypes["keep"], prototypes["drop"]
    keep_vectors = await embed_texts(keep_sentences) if keep_sentences else []
    drop_vectors = await embed_texts(drop_sentences) if drop_sentences else []

    results = []
    for row in rows:
        text = row.get("text")
        prefiltered = lexical_prefilter(text)
        if prefiltered is not None:
            results.append({"doc_id": row["doc_id"], "gate_band": prefiltered, "gate_score": None})
            continue

        vector = row.get("vector")
        if vector is None or not (keep_vectors or drop_vectors):
            # No embedding or no prototypes configured yet — can't judge
            # similarity, so it's honestly ambiguous rather than a guess.
            results.append({"doc_id": row["doc_id"], "gate_band": "ambiguous", "gate_score": None})
            continue

        band, score = embedding_similarity_band(vector, keep_vectors, drop_vectors)
        results.append({"doc_id": row["doc_id"], "gate_band": band, "gate_score": score})
    return results
