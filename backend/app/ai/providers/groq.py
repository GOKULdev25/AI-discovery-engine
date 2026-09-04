"""Groq Llama 3.1 8B — interactive work and Gemini failover (A§11.1): 30
RPM but only 6,000 TPM, the binding constraint that makes it unsuitable for
bulk classification on its own. OpenAI-compatible chat completions REST.
"""

from __future__ import annotations

import json

import httpx

from app.ai.providers.base import (
    ProviderAuthError,
    ProviderLimits,
    ProviderParseError,
    ProviderQuotaExhausted,
    ProviderResponse,
    ProviderUnavailable,
    estimate_tokens_from_chars,
)

LIMITS = ProviderLimits(rpm=30, tpm=6_000, rpd=14_400)

_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    id = "groq"
    limits = LIMITS

    def __init__(self, api_key: str, model: str, http_client: httpx.AsyncClient):
        self._api_key = api_key
        self._model = model
        self._http = http_client

    def estimate_tokens(self, prompt: str) -> int:
        return estimate_tokens_from_chars(prompt)

    async def complete_json(self, prompt: str) -> ProviderResponse:
        try:
            resp = await self._http.post(
                _URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=30.0,
            )
        except httpx.TransportError as exc:
            # Same reasoning as gemini.py: transient/provider-specific,
            # so the router should fail over rather than treat it as a
            # batch-scoped schema problem.
            raise ProviderUnavailable(f"groq: transport error: {exc}") from exc

        if resp.status_code == 429:
            raise ProviderQuotaExhausted(f"groq: {resp.status_code} {resp.text[:200]}")
        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"groq: {resp.status_code} {resp.text[:200]}")
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"groq: {resp.status_code} {resp.text[:200]}")
        if resp.status_code >= 400:
            # Same reasoning as gemini.py's 4xx branch, which was fixed
            # for this on 2026-08-29 while groq/ollama were left behind:
            # a non-2xx means the model never generated anything to
            # parse, so it is a configuration or availability problem,
            # not a batch/schema one. `ProviderParseError` is
            # deliberately never failed over (router.py's docstring,
            # EV-P3-08), so labelling it that way stranded the call on
            # one provider *and* escaped every caller's
            # `except ProviderQuotaExhausted`, surfacing as
            # `EXTRACTOR_CRASH`. Found live: `allam-2-7b` answers
            # `HTTP 400 Failed to generate JSON` on json_object requests
            # it cannot satisfy, which crashed 5 Lane 3 links.
            raise ProviderUnavailable(f"groq: HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
            data = json.loads(text)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderParseError(f"groq: unparseable response: {exc}") from exc

        usage = body.get("usage") or {}
        tokens_used = usage.get("total_tokens")
        return ProviderResponse(data=data, tokens_used=tokens_used)
