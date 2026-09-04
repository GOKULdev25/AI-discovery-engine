"""A scripted, deterministic, fully offline provider (EVAL.md §3.4). The
entire Phase 3 eval suite runs against this, never a real provider —
`EV-INV-14` fails the run if a single free-tier request goes out. Real
providers (`gemini.py`, `groq.py`, `ollama.py`) are exercised only by an
explicit `--live` run, never by the default suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.providers.base import (
    Provider,
    ProviderAuthError,
    ProviderError,
    ProviderLimits,
    ProviderParseError,
    ProviderQuotaExhausted,
    ProviderResponse,
    estimate_tokens_from_chars,
)


@dataclass
class FakeProvider:
    """`script`: a list consumed one call at a time. Each entry is either a
    JSON-serializable value (returned as `ProviderResponse.data`, with
    `tokens_used` estimated from the prompt unless overridden) or an
    `Exception` instance (raised as-is). Exhausting the script raises
    `ProviderQuotaExhausted` — a test that expects more calls than it
    scripted is a bug in the test, not a hang against a real network."""

    id: str
    limits: ProviderLimits
    script: list[Any] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # every prompt received, in order — eval assertions read this

    def estimate_tokens(self, prompt: str) -> int:
        return estimate_tokens_from_chars(prompt)

    async def complete_json(self, prompt: str) -> ProviderResponse:
        self.calls.append(prompt)
        if not self.script:
            raise ProviderQuotaExhausted(f"{self.id}: fake provider's script is exhausted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        if isinstance(item, Exception):
            raise item
        return ProviderResponse(data=item, tokens_used=self.estimate_tokens(prompt))


def gemini_like(script: list[Any] | None = None) -> FakeProvider:
    return FakeProvider(
        id="gemini", limits=ProviderLimits(rpm=10, tpm=250_000, rpd=500), script=script or []
    )


def groq_like(script: list[Any] | None = None) -> FakeProvider:
    return FakeProvider(
        id="groq", limits=ProviderLimits(rpm=30, tpm=6_000, rpd=14_400), script=script or []
    )


def ollama_like(script: list[Any] | None = None) -> FakeProvider:
    return FakeProvider(id="ollama", limits=ProviderLimits(rpm=None, tpm=None, rpd=None), script=script or [])


__all__ = [
    "FakeProvider",
    "gemini_like",
    "groq_like",
    "ollama_like",
    "ProviderAuthError",
    "ProviderParseError",
    "ProviderQuotaExhausted",
]
