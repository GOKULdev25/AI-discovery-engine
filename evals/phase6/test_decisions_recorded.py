"""EV-P6-12 — A§16.2 (is Amazon worth it at its logged-out ceiling?)
answered in writing, with the measured review counts, not left as an
open question past this phase's close."""

from __future__ import annotations

from evals.harness import REPO_ROOT
from evals.registry import eval_case


@eval_case(
    "EV-P6-12",
    proves="Docs/DECISIONS.md records A§16.2 with measured review counts",
    source="A§16.2",
    severity="MAJOR",
    tags=["phase:P6"],
)
def ev_p6_12():
    path = REPO_ROOT / "Docs" / "DECISIONS.md"
    assert path.exists(), "Docs/DECISIONS.md must exist by Phase 6 close"
    text = path.read_text(encoding="utf-8")
    assert "A§16.2" in text, "the Amazon decision must reference A§16.2 explicitly"
    assert "A§16.1" in text, "the session_mode decision (A§16.1) must also be recorded"
    assert any(word in text for word in ("Decision:", "**Decision")), "the entry must state an actual decision, not just discuss the question"
    # A real measured number, not a restatement of the plan's own 8-13 claim.
    import re

    assert re.search(r"\b\d{1,2}(,\s*\d{1,2}){0,2}\b.*review", text), (
        "expected a measured review count recorded in the decision, not just the architecture's original range"
    )
