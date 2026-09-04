"""EV-P5-13 — chat's interactive routing is inverted from Phase 3's bulk
routing (A§11.1): Groq first (latency is what a chat user feels), Gemini
as failover."""

from __future__ import annotations

from app.ai.providers.factory import build_chat_providers, build_providers
from app.config import Settings
from evals.registry import eval_case


@eval_case(
    "EV-P5-13",
    proves="Chat turns go to Groq first, failover Gemini — the mirror image of Phase 3's bulk classification order",
    source="A§11.1",
    severity="MINOR",
    tags=["phase:P5"],
)
def ev_p5_13():
    settings = Settings(gemini_api_key="fake-gemini-key", groq_api_key="fake-groq-key")
    # Neither factory calls the client — it's only threaded into the
    # provider constructors for later use — so a bare sentinel is enough.
    client = object()
    chat_providers = build_chat_providers(settings, client)
    bulk_providers = build_providers(settings, client)

    assert [p.id for p in chat_providers[:2]] == ["groq", "gemini"], "chat must try Groq before Gemini"
    assert [p.id for p in bulk_providers[:2]] == ["gemini", "groq"], "bulk classification must try Gemini before Groq"
    assert chat_providers[-1].id == "ollama" and bulk_providers[-1].id == "ollama"
