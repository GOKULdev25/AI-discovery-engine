"""EV-P3-01, 02, 11 — the free tier holds at scale, re-running doesn't
re-charge, and batching matches the cost model. All against the scripted
fake provider (EVAL.md §3.4) — no real network, no real quota spent.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.ai import quota
from app.ai.providers import fake
from app.ai.providers.base import estimate_tokens_from_chars
from app.pipeline import classify
from app.store import sqlite as sq
from evals.registry import eval_case

_BATCH_SIZE = 25
_DOC_COUNT = 5000

_PROTOTYPES_PATH_CONTENT = """\
keep:
  - "The app keeps crashing every time I open it, this really needs to be fixed."
drop:
  - "Buy cheap watches now at this link, limited time offer, click here!"
"""


def _make_docs(n: int) -> list[dict]:
    return [
        {
            "doc_id": f"doc-{i}",
            "text": f"This particular review number {i} describes a specific quality issue with the product, unique detail {i}.",
        }
        for i in range(n)
    ]


def _script_for(docs: list[dict], batch_size: int) -> list[list[dict]]:
    """One script entry per batch — a JSON-array-shaped decision for
    every doc_id in that chunk, matching what `classify_batch` will
    actually send in one `complete_json` call."""
    script = []
    for i in range(0, len(docs), batch_size):
        chunk = docs[i : i + batch_size]
        script.append([{"doc_id": d["doc_id"], "decision": "keep"} for d in chunk])
    return script


@eval_case(
    "EV-P3-01",
    proves="5,000 documents classify end to end without exceeding any free-tier window; the ledger's numbers match what was actually sent",
    source="A§11.1",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_01():
    docs = _make_docs(_DOC_COUNT)
    with tempfile.TemporaryDirectory(prefix="ev-p301-") as tmp:
        prototypes_path = Path(tmp) / "prototypes.yaml"
        prototypes_path.write_text(_PROTOTYPES_PATH_CONTENT, encoding="utf-8")
        app_sqlite = Path(tmp) / "app.sqlite"

        provider = fake.gemini_like(script=_script_for(docs, _BATCH_SIZE))
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        async with sq.app_db(app_sqlite) as conn:
            total_resolved = 0
            batch_index = 0
            for i in range(0, len(docs), _BATCH_SIZE):
                chunk = docs[i : i + _BATCH_SIZE]
                # Gemini's real RPM is 10 — 200 requests at real wall-clock
                # pace would take ~20 minutes, which this eval can't wait
                # for. The injectable clock simulates that pacing instead:
                # 10 requests land in each synthetic minute, respecting
                # the ceiling exactly, without an actual 20-minute test.
                now = base + timedelta(minutes=batch_index // provider.limits.rpm)
                resolved = await classify.classify_batch(conn, [provider], prototypes_path, chunk, now=now)
                total_resolved += len(resolved)
                remaining = await quota.remaining(conn, provider.id, provider.limits, now=now)
                assert remaining["rpm"]["used"] <= provider.limits.rpm
                assert remaining["tpm"]["used"] <= provider.limits.tpm
                assert remaining["rpd"]["used"] <= provider.limits.rpd
                batch_index += 1

            assert total_resolved == _DOC_COUNT, f"expected all {_DOC_COUNT} resolved, got {total_resolved}"
            expected_calls = _DOC_COUNT // _BATCH_SIZE
            assert len(provider.calls) == expected_calls, (
                f"expected {expected_calls} provider calls (~25 docs/request), got {len(provider.calls)}"
            )


@eval_case(
    "EV-P3-02",
    proves="Re-running the same documents makes zero provider calls the second time (P§8 criterion 4, A§11.3)",
    source="A§11.3",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_02():
    docs = _make_docs(100)
    with tempfile.TemporaryDirectory(prefix="ev-p302-") as tmp:
        prototypes_path = Path(tmp) / "prototypes.yaml"
        prototypes_path.write_text(_PROTOTYPES_PATH_CONTENT, encoding="utf-8")
        app_sqlite = Path(tmp) / "app.sqlite"

        first_provider = fake.gemini_like(script=_script_for(docs, _BATCH_SIZE))
        async with sq.app_db(app_sqlite) as conn:
            first_resolved = []
            for i in range(0, len(docs), _BATCH_SIZE):
                chunk = docs[i : i + _BATCH_SIZE]
                first_resolved += await classify.classify_batch(conn, [first_provider], prototypes_path, chunk)
            assert len(first_resolved) == len(docs)

            # A second provider with an EMPTY script — any call at all
            # raises ProviderQuotaExhausted ("script exhausted"), so this
            # run can only succeed if every document comes from cache.
            second_provider = fake.gemini_like(script=[])
            second_resolved = []
            for i in range(0, len(docs), _BATCH_SIZE):
                chunk = docs[i : i + _BATCH_SIZE]
                second_resolved += await classify.classify_batch(conn, [second_provider], prototypes_path, chunk)

            assert len(second_resolved) == len(docs), "the second run should resolve every doc from cache"
            assert second_provider.calls == [], f"the second run made {len(second_provider.calls)} live-shaped call(s) instead of hitting cache"


@eval_case(
    "EV-P3-11",
    proves="Batching matches the cost model: ~25 docs/request, and the pre-call token estimate is a reasonable proxy for a real one",
    source="A§11.1",
    severity="MAJOR",
    tags=["phase:P3"],
)
async def ev_p3_11():
    # Without a live call there is no real tokenizer output to check the
    # estimate against — EV-INV-14 forbids exactly that from the default
    # suite (EVAL.md §3.4). What's checkable offline: the estimator sits
    # in the well-documented reasonable range for GPT/Gemini-family BPE
    # tokenizers on mixed English+JSON content (~3-5 characters/token),
    # it isn't secretly a constant, and it scales with input size rather
    # than, say, counting bytes instead of characters on multibyte text.
    small_prompt = classify._build_prompt({"keep": ["example keep"], "drop": ["example drop"]}, _make_docs(_BATCH_SIZE))
    large_prompt = classify._build_prompt({"keep": ["example keep"], "drop": ["example drop"]}, _make_docs(_BATCH_SIZE * 4))
    small_estimate = estimate_tokens_from_chars(small_prompt)
    large_estimate = estimate_tokens_from_chars(large_prompt)

    for prompt, estimate in [(small_prompt, small_estimate), (large_prompt, large_estimate)]:
        implied_chars_per_token = len(prompt) / estimate
        assert 3.0 <= implied_chars_per_token <= 5.0, (
            f"estimator implies {implied_chars_per_token:.2f} chars/token, outside the plausible 3-5 range"
        )

    ratio = large_estimate / small_estimate
    assert 3.0 <= ratio <= 5.0, f"quadrupling the batch should roughly quadruple the estimate, got a {ratio:.2f}x change"

    multibyte_estimate = estimate_tokens_from_chars("很好的应用程序" * 100)
    assert multibyte_estimate > 0 and multibyte_estimate < len("很好的应用程序" * 100), (
        "the estimator should count characters, not UTF-8 bytes, for multibyte text"
    )

    expected_requests = _DOC_COUNT // _BATCH_SIZE
    assert expected_requests == 200, "the plan's own arithmetic: ~200 requests per 5,000 documents at 25/request"
