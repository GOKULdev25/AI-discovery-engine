"""Ollama — optional local fallback (A§11.1). Not a metered tier (no RPM/
TPM/RPD to track), so exhausting Gemini and Groq degrades to this instead
of failing the run outright. If nothing is listening on `OLLAMA_BASE_URL`
(the common case — it's optional), that's `ProviderUnavailable`, not a
crash: the router moves on to "requeue for tomorrow" exactly as if this
were one more exhausted quota.
"""

from __future__ import annotations

import json

import httpx

from app.ai.providers.base import (
    ProviderLimits,
    ProviderParseError,
    ProviderResponse,
    ProviderUnavailable,
    estimate_tokens_from_chars,
)

LIMITS = ProviderLimits(rpm=None, tpm=None, rpd=None)


class OllamaProvider:
    id = "ollama"
    limits = LIMITS

    def __init__(self, base_url: str, model: str, http_client: httpx.AsyncClient):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = http_client

    def estimate_tokens(self, prompt: str) -> int:
        return estimate_tokens_from_chars(prompt)

    async def complete_json(self, prompt: str) -> ProviderResponse:
        try:
            resp = await self._http.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "format": "json", "stream": False},
                timeout=60.0,
            )
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"ollama: unreachable at {self._base_url}: {exc}") from exc

        if resp.status_code >= 500:
            raise ProviderUnavailable(f"ollama: {resp.status_code} {resp.text[:200]}")
        if resp.status_code >= 400:
            # See gemini.py's 4xx branch: a non-2xx means nothing was
            # generated to parse — an availability/config problem (an
            # unpulled model 404s here), not a schema one. Labelling it
            # `ProviderParseError` would stop failover dead, since
            # router.py deliberately never fails over on that.
            raise ProviderUnavailable(f"ollama: HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            body = resp.json()
            data = json.loads(body["response"])
        except (KeyError, ValueError) as exc:
            raise ProviderParseError(f"ollama: unparseable response: {exc}") from exc

        tokens_used = None
        if "eval_count" in body or "prompt_eval_count" in body:
            tokens_used = body.get("eval_count", 0) + body.get("prompt_eval_count", 0)
        return ProviderResponse(data=data, tokens_used=tokens_used)
