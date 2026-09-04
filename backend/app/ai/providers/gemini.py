"""Gemini Flash — bulk classification workhorse (A§11.1): ~10 RPM but
250,000 TPM, the opposite shape of Groq. REST directly via httpx rather than
the `google-generativeai` SDK — one more heavy dependency for a single
endpoint this codebase already knows how to call (IP§0.3's plain-tools
preference).
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

LIMITS = ProviderLimits(rpm=10, tpm=250_000, rpd=500)


class GeminiProvider:
    id = "gemini"
    limits = LIMITS

    def __init__(self, api_key: str, model: str, http_client: httpx.AsyncClient):
        self._api_key = api_key
        self._model = model
        self._http = http_client

    def estimate_tokens(self, prompt: str) -> int:
        return estimate_tokens_from_chars(prompt)

    async def complete_json(self, prompt: str) -> ProviderResponse:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        try:
            resp = await self._http.post(
                url,
                params={"key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=30.0,
            )
        except httpx.TransportError as exc:
            # A timeout or connection failure is transient and provider-
            # specific, not a batch/schema problem — the router should
            # fail over to the next provider, same as an exhausted quota
            # (found live, 2026-08-29: a real Gemini ReadTimeout was
            # otherwise stuck at ProviderParseError, which never fails
            # over, leaving a perfectly good Groq unused).
            raise ProviderUnavailable(f"gemini: transport error: {exc}") from exc

        if resp.status_code == 429:
            raise ProviderQuotaExhausted(f"gemini: {resp.status_code} {resp.text[:200]}")
        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"gemini: {resp.status_code} {resp.text[:200]}")
        if resp.status_code >= 400:
            # Any other non-2xx (400 bad request, 404 unknown model, 5xx
            # overloaded/maintenance) means the model never generated
            # anything to parse — a configuration or availability
            # problem, not a batch/schema one. Found live, 2026-08-29: a
            # bad model name returned 404 and was originally
            # miscategorized as ProviderParseError here, which never
            # fails over — see ProviderUnavailable's docstring.
            raise ProviderUnavailable(f"gemini: HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            body = resp.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderParseError(f"gemini: unparseable response: {exc}") from exc

        usage = body.get("usageMetadata") or {}
        tokens_used = usage.get("totalTokenCount")
        return ProviderResponse(data=data, tokens_used=tokens_used)
