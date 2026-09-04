"""Orchestrates local enrichment + the gate over newly-committed
documents (A§11.2) and writes results back through the project's
single-writer `Committer`. Called after every staging drain
(`pipeline/commit.py`) — enrichment is resumable and idempotent by
construction: it always re-queries for documents with no `enrichment`
row yet, so a crash between drain and enrichment just means the next
drain cycle picks the same documents back up.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.pipeline import enrich_local, gate
from app.sources.profiles import get_profile
from app.store.duckdb import Committer, unpack_embedding

BATCH_SIZE = 200


def normalize_engagement(
    source: str, engagement_raw: object
) -> tuple[int | None, str | None]:
    """Pull the one comparable engagement number out of a source's
    `engagement` JSON blob, per that source's declared profile.

    Returns `(count, kind)`. `kind` is the source's own word for the
    metric (`likes`, `score`, `helpful`, ...) and always travels with the
    number, because these are not interchangeable quantities — see
    `0003_engagement.sql`.

    Every failure mode returns `(None, None)` rather than 0: a source
    with no engagement metric, a blob that doesn't parse, a missing key,
    and a non-numeric value are all "we don't know", and P§6 says an
    unknown stays null instead of becoming a plausible-looking zero.
    """
    spec = get_profile(source).engagement
    if spec is None or engagement_raw is None:
        return None, None

    blob = engagement_raw
    if isinstance(blob, (str, bytes)):
        try:
            blob = json.loads(blob)
        except (ValueError, TypeError):
            return None, None
    if not isinstance(blob, dict):
        return None, None

    value = blob.get(spec.key)
    if value is None:
        return None, None
    try:
        # App Store returns these as strings ("im:voteSum" is a label),
        # YouTube as ints — coerce through float so "12" and 12 both land.
        return int(float(value)), spec.key
    except (ValueError, TypeError):
        return None, None


async def enrich_pending_documents(project_dir: Path, committer: Committer) -> int:
    reader = committer.cursor()
    rows = reader.execute(
        """SELECT d.doc_id, d.text, d.source, d.engagement FROM documents d
           LEFT JOIN enrichment e ON d.doc_id = e.doc_id
           WHERE e.doc_id IS NULL
           LIMIT ?""",
        [BATCH_SIZE],
    ).fetchall()
    if not rows:
        return 0

    doc_dicts = [{"doc_id": r[0], "text": r[1]} for r in rows]
    text_by_id = {d["doc_id"]: d["text"] for d in doc_dicts}
    engagement_by_id = {
        r[0]: normalize_engagement(r[2], r[3]) for r in rows
    }

    enriched = await enrich_local.enrich_documents(doc_dicts)

    prototypes_path = project_dir / "gate" / "prototypes.yaml"
    gate_input = [
        {"doc_id": e["doc_id"], "text": text_by_id[e["doc_id"]], "vector": e["vector"]}
        for e in enriched
    ]
    gate_results = await gate.gate_documents(gate_input, prototypes_path)
    gate_by_id = {g["doc_id"]: g for g in gate_results}

    lang_updates = [(e["doc_id"], e["lang"]) for e in enriched if e["lang"]]
    await committer.update_lang(lang_updates)

    enrichment_rows = [
        {
            "doc_id": e["doc_id"],
            "lang_confidence": e["lang_confidence"],
            "sentiment_prior": e["sentiment_prior"],
            "simhash": e["simhash"],
            "gate_band": gate_by_id[e["doc_id"]]["gate_band"],
            "gate_score": gate_by_id[e["doc_id"]]["gate_score"],
            "engagement_count": engagement_by_id[e["doc_id"]][0],
            "engagement_kind": engagement_by_id[e["doc_id"]][1],
        }
        for e in enriched
    ]
    await committer.upsert_enrichment(enrichment_rows)

    embed_rows = [
        {"doc_id": e["doc_id"], "model": enrich_local.EMBEDDING_MODEL, "vector": e["vector"]}
        for e in enriched
        if e["vector"] is not None
    ]
    await committer.insert_embeddings(embed_rows)

    return len(rows)


async def regate_documents(project_dir: Path, committer: Committer) -> int:
    """Re-runs the embedding gate over every already-enriched document,
    against whatever prototypes are on disk now.

    Used when a project's `gate/prototypes.yaml` is edited. It reuses the
    stored embeddings rather than re-deriving anything: a prototype change
    moves only the keep-vs-drop comparison, so language, sentiment prior,
    simhash and the vectors themselves are all still valid. That also
    makes this free and offline — no model call, no network.

    Deliberately not expressed as "clear the bands and let enrichment
    redo it": `enrich_pending_documents` only ever looks at documents with
    no `enrichment` row at all, so nulling a column would re-gate nothing.
    """
    reader = committer.cursor()
    rows = reader.execute(
        """SELECT d.doc_id, d.text, em.vector, em.dim
           FROM documents d
           JOIN enrichment e ON d.doc_id = e.doc_id
           LEFT JOIN embeddings em ON d.doc_id = em.doc_id"""
    ).fetchall()
    if not rows:
        return 0

    gate_input = [
        {
            "doc_id": r[0],
            "text": r[1],
            "vector": unpack_embedding(r[2], r[3]) if r[2] is not None and r[3] else None,
        }
        for r in rows
    ]
    prototypes_path = project_dir / "gate" / "prototypes.yaml"
    results = await gate.gate_documents(gate_input, prototypes_path)

    updates = [(g["doc_id"], g["gate_band"], g["gate_score"]) for g in results]
    for i in range(0, len(updates), BATCH_SIZE):
        await committer.update_gate_band(updates[i : i + BATCH_SIZE])
    return len(updates)
