"""The `project.yaml` schema (IP§0.2, A§7.1). Every per-project policy
decision — session_mode, enabled sources, locale fan-out, rate overrides,
gate settings — lives here, not in a global default that could apply
silently (A§5.3, decision 1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_ENABLED_SOURCES = ["youtube", "reddit", "appstore", "playstore"]

# A§16.3 decision 3: a conservative 3-locale default, so coverage is a
# deliberate choice shown to the operator, not an accident of "let's try
# every country code."
DEFAULT_LOCALES = ["us", "in", "gb"]


class ProjectConfig(BaseModel):
    id: str
    name: str
    created_at: str

    # Decision 1 (A§16.1): default ships strictly within P§6 as written.
    # `operator_session` must be an explicit per-project opt-in, never a
    # config default someone inherits by accident (A§5.3).
    session_mode: Literal["logged_out", "operator_session"] = "logged_out"

    enabled_sources: list[str] = Field(default_factory=lambda: list(DEFAULT_ENABLED_SOURCES))
    locales: list[str] = Field(default_factory=lambda: list(DEFAULT_LOCALES))
    rate_overrides: dict[str, dict] = Field(default_factory=dict)
    gate: dict = Field(default_factory=dict)
