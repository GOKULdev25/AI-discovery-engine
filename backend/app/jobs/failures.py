"""The A§8.1 failure taxonomy. An enum, not strings — every code carries a
fixed `retryable` flag so the UI, the retry endpoint, and the router (P3)
never have to guess. Every failure path in every phase must terminate in
one of these codes (IP§0.5); a bare `except Exception` that logs and
continues is a blocker (EV-INV-07).
"""

from __future__ import annotations

from enum import Enum


class FailureCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    NOT_FOUND = "NOT_FOUND"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    BLOCKED_ANTIBOT = "BLOCKED_ANTIBOT"
    PARSE_ERROR = "PARSE_ERROR"
    EMPTY_RESULT = "EMPTY_RESULT"
    EXTRACTOR_CRASH = "EXTRACTOR_CRASH"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    NETWORK_ERROR = "NETWORK_ERROR"


_RETRYABLE = {
    FailureCode.RATE_LIMITED,
    FailureCode.QUOTA_EXHAUSTED,
    FailureCode.NETWORK_ERROR,
}


def is_retryable(code: FailureCode) -> bool:
    return code in _RETRYABLE


class ExtractionError(Exception):
    """Every connector/lane raises this, never a bare Exception, so a
    failure always carries a typed code on its way to the API (EV-INV-12)."""

    def __init__(self, code: FailureCode, message: str = ""):
        self.code = code
        self.retryable = is_retryable(code)
        super().__init__(message or code.value)


class LaneDowngrade:
    """Not a failure — a first-class visible event (A§4). Emitted, never
    just logged, when a link falls from Lane 1 to Lane 2 or Lane 2 to
    Lane 3."""

    def __init__(self, from_lane: str, to_lane: str, reason: str):
        self.from_lane = from_lane
        self.to_lane = to_lane
        self.reason = reason
