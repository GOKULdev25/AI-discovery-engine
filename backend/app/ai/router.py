"""Provider selection and failover (A§11.1, A§11.3). `pipeline/classify.py`
never talks to a provider directly — it calls `route()`, which reserves
quota, calls the first provider still willing to serve, and fails over on
exhaustion: Gemini -> Groq -> Ollama -> `ProviderQuotaExhausted` all the
way up (the caller requeues for later, A§8.1's retryable-by-design
convention applied one layer above the connector job engine).

`ProviderParseError` is deliberately NOT caught here — a malformed
response is a prompt/schema problem scoped to the batch that produced it
(EV-P3-08), not a signal that a *different* provider would do better, and
retrying it against another provider would just spend more quota on the
same broken batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from app.ai import quota
from app.ai.providers.base import Provider, ProviderAuthError, ProviderQuotaExhausted

logger = logging.getLogger("app.ai.router")


@dataclass
class RouteResult:
    data: object
    provider_id: str
    tokens_used: int | None


async def route(
    conn: aiosqlite.Connection, providers: list[Provider], prompt: str, *, now: datetime | None = None
) -> RouteResult:
    """Tries `providers` in order (caller decides the order — production
    code passes Gemini, Groq, Ollama; evals pass whatever they scripted).
    Raises `ProviderQuotaExhausted` only once every provider in the list
    has been tried and failed.

    `now` is an injectable clock, threaded straight through to
    `ai/quota.py` — production always leaves it real; a 5,000-document
    eval run (EV-P3-01) needs to simulate RPM pacing across many rolling
    minutes without a real 20-minute wait."""
    last_error: Exception | None = None
    for provider in providers:
        tokens_estimate = provider.estimate_tokens(prompt)
        try:
            await quota.reserve(conn, provider.id, provider.limits, tokens_estimate, now=now)
        except ProviderQuotaExhausted as exc:
            logger.info("quota exhausted pre-flight for %s, trying next provider", provider.id)
            last_error = exc
            continue

        try:
            response = await provider.complete_json(prompt)
        except ProviderAuthError as exc:
            logger.error("auth error for %s, trying next provider: %s", provider.id, exc)
            last_error = exc
            continue
        except ProviderQuotaExhausted as exc:
            # A live rejection despite our own ledger saying there was
            # room — the estimate was wrong, or another process spent it
            # first. Either way, this provider is done for now.
            logger.info("provider %s rejected the call as quota-exhausted, trying next", provider.id)
            last_error = exc
            continue

        await quota.record_actual(conn, provider.id, tokens_estimate, response.tokens_used, now=now)
        return RouteResult(data=response.data, provider_id=provider.id, tokens_used=response.tokens_used)

    raise ProviderQuotaExhausted(f"every provider exhausted or unavailable: {last_error}")
