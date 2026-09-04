"""`GET /quota` (A§7.3, A§13) — app-level remaining daily budget, so a
long classification run doesn't die halfway through unexplained. Reads
the same ledger `ai/router.py` reserves against; no provider client
needed here, just the limits each one reports."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai import quota
from app.ai.providers.gemini import LIMITS as GEMINI_LIMITS
from app.ai.providers.groq import LIMITS as GROQ_LIMITS
from app.ai.providers.ollama import LIMITS as OLLAMA_LIMITS
from app.api.deps import settings_dep
from app.config import Settings
from app.store import sqlite as sq

router = APIRouter(tags=["quota"])

_PROVIDER_LIMITS = [("gemini", GEMINI_LIMITS), ("groq", GROQ_LIMITS), ("ollama", OLLAMA_LIMITS)]


class WindowBudget(BaseModel):
    used: int
    limit: int | None
    remaining: int | None


class ProviderBudget(BaseModel):
    rpm: WindowBudget
    tpm: WindowBudget
    rpd: WindowBudget


class QuotaResponse(BaseModel):
    gemini: ProviderBudget
    groq: ProviderBudget
    ollama: ProviderBudget


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(settings: Settings = Depends(settings_dep)):
    async with sq.app_db(settings.app_sqlite_path) as conn:
        return {
            provider_id: await quota.remaining(conn, provider_id, limits)
            for provider_id, limits in _PROVIDER_LIMITS
        }
