"""Builds the production provider list in A§11.1's failover order:
Gemini (bulk classification) -> Groq (interactive/failover) -> Ollama
(optional local fallback, always attempted last and never required —
`OllamaProvider` degrades to `ProviderUnavailable` on its own if nothing's
listening on `OLLAMA_BASE_URL`)."""

from __future__ import annotations

import httpx

from app.ai.providers.base import Provider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.groq import GroqProvider
from app.ai.providers.ollama import OllamaProvider
from app.config import Settings


def build_providers(settings: Settings, http_client: httpx.AsyncClient) -> list[Provider]:
    """Bulk-classification order (A§11.1): Gemini first (250k TPM makes
    ~25-doc batches cheap), Groq as failover, Ollama last."""
    providers: list[Provider] = []
    if settings.gemini_api_key:
        providers.append(GeminiProvider(settings.gemini_api_key, settings.gemini_model, http_client))
    if settings.groq_api_key:
        providers.append(GroqProvider(settings.groq_api_key, settings.groq_model, http_client))
    providers.append(OllamaProvider(settings.ollama_base_url, settings.ollama_model, http_client))
    return providers


def build_chat_providers(settings: Settings, http_client: httpx.AsyncClient) -> list[Provider]:
    """Interactive order (A§11.1) — the mirror image of `build_providers`:
    Groq first (30 RPM, latency is what a chat user actually feels),
    Gemini as failover, Ollama last (EV-P5-13)."""
    providers: list[Provider] = []
    if settings.groq_api_key:
        providers.append(GroqProvider(settings.groq_api_key, settings.groq_model, http_client))
    if settings.gemini_api_key:
        providers.append(GeminiProvider(settings.gemini_api_key, settings.gemini_model, http_client))
    providers.append(OllamaProvider(settings.ollama_base_url, settings.ollama_model, http_client))
    return providers
