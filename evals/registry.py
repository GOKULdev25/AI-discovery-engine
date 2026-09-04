"""ID -> metadata (EVAL.md §1.2). An eval with no `source` fails
registration: it is either testing something nobody promised, or the
promise needs writing down first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

Severity = Literal["BLOCKER", "MAJOR", "MINOR"]

_ID_RE = re.compile(r"^EV-(P-1|P[0-7]|INV)-\d{2}$")


class EvalSkip(Exception):
    """Raised by an eval body to record a legitimate SKIP (precondition —
    usually a not-yet-built feature — absent). Illegitimate after the
    owning phase closes (EVAL.md §1.3)."""


@dataclass
class EvalDef:
    id: str
    proves: str
    source: str
    severity: Severity
    tags: list[str]
    fn: Callable[[], Awaitable[None] | None]

    def phase_tag(self) -> str | None:
        for t in self.tags:
            if t.startswith("phase:"):
                return t[len("phase:"):]
        return None


_registry: dict[str, EvalDef] = {}


def eval_case(
    id: str, *, proves: str, source: str, severity: Severity, tags: list[str]
) -> Callable[[Callable], Callable]:
    if not _ID_RE.match(id):
        raise ValueError(f"malformed eval id: {id!r}")
    if not source:
        raise ValueError(f"{id}: an eval with no `source` is suspect — see EVAL.md §1.2")

    def deco(fn: Callable) -> Callable:
        if id in _registry:
            raise ValueError(f"duplicate eval id: {id}")
        _registry[id] = EvalDef(id=id, proves=proves, source=source, severity=severity, tags=list(tags), fn=fn)
        return fn

    return deco


def all_evals() -> list[EvalDef]:
    return sorted(_registry.values(), key=lambda e: e.id)


def get(eval_id: str) -> EvalDef | None:
    return _registry.get(eval_id)


def clear_for_tests() -> None:
    _registry.clear()
