"""Local enrichment (A§11.2) — everything here is CPU-local, free, and
unlimited: language detection, a lexicon sentiment *prior* (never the
final label — that's Phase 3's LLM job), and `fastembed` embeddings.
Closes the "unfunded mandate" C§9.1 flagged: most of sentiment's work
costs nothing.
"""

from __future__ import annotations

import asyncio

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.pipeline.dedup import compute_simhash

# langdetect's detection is otherwise non-deterministic (it seeds off
# wall-clock time internally) — pinned so the same text always gets the
# same language across runs and restarts.
DetectorFactory.seed = 0

LANG_CONFIDENCE_FLOOR = 0.5  # below this, lang stays null rather than guessing (EV-P2-12)
# langdetect has no real signal on very short strings — it reports
# near-1.0 confidence for outright wrong guesses ("ok" -> Slovak at
# 0.9999, "nice" -> Polish at 0.9999), so the confidence floor above
# can't catch these; a length floor is the only thing that does
# (EV-P2-12).
MIN_CHARS_FOR_LANG_DETECTION = 10
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_analyzer: SentimentIntensityAnalyzer | None = None
_embedder = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def _get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _embedder


def embeddings_enabled() -> bool:
    """Settings.embeddings_enabled, read through config.py (the only
    module allowed to touch the environment — EV-INV-03). Imported
    locally so this module stays importable in isolation, the same way
    gate.py imports back into here."""
    from app.config import get_settings

    return get_settings().embeddings_enabled


async def warmup() -> None:
    """Loading the embedding model costs ~10s (ONNX model fetch/init) —
    pay it once at API startup, not on the first document (the same
    reasoning as `app/http_client.py`'s SSL-context warmup)."""
    if embeddings_enabled():
        await asyncio.to_thread(_get_embedder)
    _get_analyzer()  # no model to load; just avoids a cold first call


def detect_language(text: str | None) -> tuple[str | None, float | None]:
    """Returns (lang, confidence). Low confidence or undetectable text
    stays (None, None) — never a guess presented as fact."""
    stripped = (text or "").strip()
    if len(stripped) < MIN_CHARS_FOR_LANG_DETECTION:
        return None, None
    try:
        candidates = detect_langs(stripped)
    except LangDetectException:
        return None, None
    if not candidates:
        return None, None
    top = candidates[0]
    if top.prob < LANG_CONFIDENCE_FLOOR:
        return None, top.prob
    return top.lang, top.prob


_MAX_CHARS_FOR_SENTIMENT = 5000  # VADER's polarity_scores is quadratic in
# input length here (measured: 57k chars -> 17.4s, 5k chars -> 0.15s) —
# a real DoS-shaped hazard, since one long document blocks the whole
# enrichment batch it's drained with (EV-P2-13). Sentiment signal doesn't
# meaningfully improve past a few thousand characters anyway, and this is
# a prior, never the final label.


def sentiment_prior(text: str | None) -> float | None:
    """VADER compound score in [-1, 1] — a *prior*, stored in its own
    column, never presented as the final label (P§6, A§11.2)."""
    if not text or not text.strip():
        return None
    return _get_analyzer().polarity_scores(text[:_MAX_CHARS_FOR_SENTIMENT])["compound"]


_LONG_TEXT_CHAR_THRESHOLD = 500  # ONNX inference on a batch pads every
# sequence up to the batch's longest one — one near-max-length document
# (bge-small truncates at 512 tokens either way) mixed into a batch of
# short reviews inflates every short one to that same padded cost. Measured
# on this machine: 8 texts (one 57k chars) batched together took 10.3s;
# the same 8 embedded one-at-a-time totalled 3.4s. Splitting short and long
# text into separate `embed()` calls keeps the common case (a batch that's
# almost entirely normal-length reviews) fast without ever changing what
# gets embedded (EV-P2-13).


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batched fastembed call, off the event loop (ONNX inference is
    blocking CPU work). Returns `[]` when embeddings are disabled for
    this deployment — every caller already treats a missing vector as
    "can't judge this" rather than as a zero: gate.py bands it
    `ambiguous`, retrieval.py drops the vector half of the hybrid and
    runs BM25 alone. Nothing downstream invents a value."""
    if not texts or not embeddings_enabled():
        return []
    embedder = _get_embedder()

    def _run() -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        short_idx = [i for i, t in enumerate(texts) if len(t) <= _LONG_TEXT_CHAR_THRESHOLD]
        long_idx = [i for i, t in enumerate(texts) if len(t) > _LONG_TEXT_CHAR_THRESHOLD]
        if short_idx:
            for i, vec in zip(short_idx, embedder.embed([texts[i] for i in short_idx])):
                results[i] = vec.tolist()
        for i in long_idx:
            results[i] = next(iter(embedder.embed([texts[i]]))).tolist()
        return results  # type: ignore[return-value]

    return await asyncio.to_thread(_run)


async def enrich_documents(rows: list[dict]) -> list[dict]:
    """`rows`: [{"doc_id":..., "text":...}, ...]. Returns one result dict
    per input row with lang/lang_confidence/sentiment_prior/simhash/
    embedding — the caller (pipeline/gate.py or the job that triggers
    enrichment) is responsible for writing these back via the
    project's Committer."""
    texts = [r.get("text") or "" for r in rows]
    embeddings = await embed_texts([t for t in texts if t.strip()] or [""])
    embed_iter = iter(embeddings)

    results = []
    for row, text in zip(rows, texts):
        lang, confidence = detect_language(text)
        prior = sentiment_prior(text)
        simhash = compute_simhash(text)
        # `next(..., None)`, not bare `next()`: with embeddings disabled
        # `embed_texts` returns an empty list, and the vector for every
        # row is then honestly absent rather than a StopIteration.
        vector = next(embed_iter, None) if text.strip() else None
        results.append({
            "doc_id": row["doc_id"],
            "lang": lang,
            "lang_confidence": confidence,
            "sentiment_prior": prior,
            "simhash": simhash,
            "vector": vector,
        })
    return results
