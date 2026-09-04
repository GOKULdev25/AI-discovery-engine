"""EV-P5-12 — hybrid retrieval actually retrieves: recall@10 >= 0.8 on a
small labeled query set, and both halves demonstrably contribute (a
lexical-exact-match query that BM25 nails, and a paraphrase query with no
shared vocabulary that only the embedding half can find)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.chat.index_fts import bm25_search
from app.chat.retrieval import hybrid_retrieve, vector_search
from app.pipeline.enrich_local import embed_texts
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.phase5._helpers import doc_row, seed_and_index
from evals.registry import eval_case

_CORPUS = {
    "cam-crash": "The camera app crashes every single time I try to take a photo, completely unusable.",
    "battery": "Battery life has gotten so much worse since the last update, dies by noon now.",
    "checkout": "The checkout flow is confusing, I couldn't figure out how to apply my discount code.",
    "support": "Customer support never responded to my email about a billing issue for three weeks.",
    "login": "I keep getting logged out randomly, have to sign in again every few minutes.",
    "ads": "There are way too many intrusive ads now, it ruins the whole experience.",
    "sync": "My data doesn't sync properly across devices, I lose my progress constantly.",
    "ui": "The new redesign is confusing, I can't find basic settings anymore.",
    "price": "The subscription price increase is not justified by any new features.",
    "positive": "Honestly this app has been great, does exactly what I need with no issues.",
}

# (query, expected_doc_key) — a mix of near-exact lexical matches and
# paraphrases with little vocabulary overlap, so recall@10 actually
# depends on both retrieval halves, not just one.
_LABELED_QUERIES = [
    ("camera app crashes when taking a photo", "cam-crash"),
    ("battery drains faster after updating", "battery"),
    ("trouble applying a discount code at checkout", "checkout"),
    ("support team ignored my billing question", "support"),
    ("gets signed out unexpectedly", "login"),
    ("too many ads interrupting the app", "ads"),
    ("progress is lost between devices", "sync"),
    ("can't locate settings after the redesign", "ui"),
]


@eval_case(
    "EV-P5-12",
    proves="Hybrid FTS5 + vector retrieval reaches >=0.8 recall@10 on a labeled query set; both halves demonstrably contribute",
    source="EVAL.md §6.7",
    severity="MAJOR",
    tags=["phase:P5"],
)
async def ev_p5_12():
    with tempfile.TemporaryDirectory(prefix="ev-p512-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)
        config = await scaffold.create_project(settings, resolver, "p512")
        project_dir = resolver.project_dir(config.id)
        try:
            committer = await dk.get_committer(project_dir)
            async with sq.ops_db(project_dir) as ops_conn:
                await seed_and_index(committer, ops_conn, [
                    doc_row(key, config.id, text) for key, text in _CORPUS.items()
                ])
                reader = await dk.get_reader(project_dir)

                hits = 0
                for query, expected_key in _LABELED_QUERIES:
                    results = await hybrid_retrieve(ops_conn, reader, query, top_k=10)
                    if expected_key in {d["doc_id"] for d in results}:
                        hits += 1
                recall = hits / len(_LABELED_QUERIES)
                assert recall >= 0.8, f"recall@10 was {recall:.2f} ({hits}/{len(_LABELED_QUERIES)}), budget is >=0.8"

                # Both halves contribute: a near-exact lexical match that
                # BM25 should rank at or near the top...
                bm25_top = await bm25_search(ops_conn, "camera app crashes photo", limit=3)
                assert bm25_top and bm25_top[0][0] == "cam-crash", "BM25 should nail a near-exact lexical match"

                # ...and a paraphrase with almost no shared vocabulary
                # that only semantic similarity can find.
                query_vec = (await embed_texts(["losing saved work when switching phones"]))[0]
                vector_top = await vector_search(reader, query_vec, limit=3)
                assert vector_top and vector_top[0][0] == "sync", (
                    f"vector search should surface the paraphrased match via semantics, got {vector_top}"
                )
        finally:
            await dk.forget_committer(project_dir)
