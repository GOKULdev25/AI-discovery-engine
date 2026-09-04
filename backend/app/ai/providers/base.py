"""The provider interface (IP§3.2). Every provider (`gemini.py`, `groq.py`,
`ollama.py`, and the eval-only `fake.py`) implements this and nothing more —
routing, quota, and caching all live one layer up in `ai/router.py`, `ai/
quota.py`, `ai/cache.py`. A provider's only job is: report its own limits,
estimate a prompt's token cost before the call, and make the call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderLimits:
    """`None` means "not modeled" (Ollama is local compute, not a metered
    tier — A§11.1 only inverts Gemini vs. Groq)."""

    rpm: int | None
    tpm: int | None
    rpd: int | None


@dataclass(frozen=True)
class ProviderResponse:
    data: Any  # parsed JSON — list or dict, whatever the caller's schema expects
    tokens_used: int | None  # actual usage the provider reported, for the ledger true-up (None if unavailable)


class ProviderError(Exception):
    """Base for every typed failure a provider call can raise. `router.py`
    catches these by type, never a bare `Exception` (A§8.1 discipline
    extends to the AI layer, not just connectors)."""


class ProviderQuotaExhausted(ProviderError):
    """This provider's own limit (429 / documented quota error) was hit —
    the router fails over to the next provider (A§11.1), it does not
    retry the same one."""


class ProviderUnavailable(ProviderQuotaExhausted):
    """The provider never got as far as generating a response to parse:
    unreachable (connection refused, DNS failure, timeout — the common
    case for a local Ollama that isn't running), a 5xx (overloaded,
    under maintenance), or a request-level rejection (bad model name,
    malformed request) that's a configuration problem rather than
    anything about the batch being sent. Found live, 2026-08-29: a
    misconfigured Gemini model name returned 404 and was originally
    miscategorized as `ProviderParseError`, which never fails over —
    the router got stuck instead of trying Groq. Subclasses
    `ProviderQuotaExhausted` so the router's one failover path (`except
    ProviderQuotaExhausted`) handles all of these the same way: try the
    next provider. Reserved for anything before content generation;
    once a provider actually returns 2xx with a body, a failure to
    parse *that* body is `ProviderParseError`, not this."""


class ProviderAuthError(ProviderError):
    """Missing or rejected credentials — not retryable by failing over
    (a bad key doesn't get better on Groq), surfaced so the run can be
    diagnosed rather than silently stuck retrying."""


class ProviderParseError(ProviderError):
    """The provider responded, but not with parseable/schema-conformant
    JSON. Scoped to the one batch that produced it (EV-P3-08) — never a
    reason to fail over or crash the run."""


class Provider(Protocol):
    id: str
    limits: ProviderLimits

    def estimate_tokens(self, prompt: str) -> int:
        """A cheap pre-call estimate for the quota ledger's TPM reservation
        (EV-P3-11: within 20% of actual). The real usage, once known from
        the response, is what the ledger is trued up to — this only needs
        to be good enough to reserve against before spending the request."""
        ...

    async def complete_json(self, prompt: str) -> ProviderResponse:
        """Sends `prompt` and returns parsed JSON plus actual token usage.
        Raises `ProviderQuotaExhausted`, `ProviderAuthError`, or
        `ProviderParseError` — never a bare exception for an expected
        failure mode."""
        ...


def estimate_tokens_from_chars(text: str) -> int:
    """~4 characters per token is the standard rough estimate for English
    text across these model families — shared by every real provider so
    the heuristic doesn't drift between them."""
    return max(1, len(text) // 4)
