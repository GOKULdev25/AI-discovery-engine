"""EV-P5-05, 06 — cross-source and cross-time caveats. Computed
structurally from the retrieved evidence itself (`grounding.compute_caveats`),
not extracted from the model's prose, so the caveat reaches the caller
even if the LLM's own answer text forgets to mention it (A§12 rules 5/6).
"""

from __future__ import annotations

from app.chat import grounding
from evals.registry import eval_case


@eval_case(
    "EV-P5-05",
    proves="A Play-Store-vs-Reddit question carries the not-directly-comparable caveat",
    source="A§12",
    severity="MAJOR",
    tags=["phase:P5"],
)
def ev_p5_05():
    single_source = [
        {"doc_id": "d1", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z"},
        {"doc_id": "d2", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z"},
    ]
    assert grounding.compute_caveats(single_source)["cross_source"] is False

    mixed_source = [
        {"doc_id": "d1", "source": "playstore", "captured_at": "2026-08-29T00:00:00Z", "text": "great app"},
        {"doc_id": "d2", "source": "reddit", "captured_at": "2026-08-29T00:00:00Z", "text": "not bad"},
    ]
    assert grounding.compute_caveats(mixed_source)["cross_source"] is True

    # And the caveat actually reaches the prompt's instructions when set.
    prompt = grounding.build_prompt("q", mixed_source, {"cross_source": True, "cross_time": False})
    assert "not directly comparable" in prompt.lower()


@eval_case(
    "EV-P5-06",
    proves="A trend question states that collection volume changed, not just sentiment",
    source="A§12",
    severity="MAJOR",
    tags=["phase:P5"],
)
def ev_p5_06():
    same_day = [
        {"doc_id": "d1", "source": "playstore", "captured_at": "2026-08-29T00:00:00+00:00"},
        {"doc_id": "d2", "source": "playstore", "captured_at": "2026-08-29T12:00:00+00:00"},
    ]
    assert grounding.compute_caveats(same_day)["cross_time"] is False

    wide_span = [
        {"doc_id": "d1", "source": "playstore", "captured_at": "2026-01-01T00:00:00+00:00", "text": "old review"},
        {"doc_id": "d2", "source": "playstore", "captured_at": "2026-08-29T00:00:00+00:00", "text": "recent review"},
    ]
    assert grounding.compute_caveats(wide_span)["cross_time"] is True

    prompt = grounding.build_prompt("q", wide_span, {"cross_source": False, "cross_time": True})
    assert "collection" in prompt.lower() and "volume" in prompt.lower()
