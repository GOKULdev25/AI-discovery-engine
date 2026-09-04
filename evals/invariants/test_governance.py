"""EV-INV-15..17 — governance over the eval system itself: the phase
marker can't outrun recorded evidence, prompt changes force a P5 re-run
once prompts exist, and every eval's `source` resolves to a real doc
section."""

from __future__ import annotations

import json
import re

from evals.harness import REPO_ROOT
from evals.registry import EvalSkip, all_evals, eval_case

PHASES = ["P-1", "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"]
CLOSE_HISTORY = REPO_ROOT / "evals" / "reports" / "close_history.json"
EVAL_PHASE_MARKER = REPO_ROOT / ".claude" / "eval-phase"
PROMPT_SIGNATURES = REPO_ROOT / "evals" / "reports" / "prompt_signatures.json"

_DOC_FILES = {
    "A": REPO_ROOT / "Docs" / "ARCHITECTURE.md",
    "IP": REPO_ROOT / "Docs" / "IMPLEMENTATION_PLAN.md",
    "P": REPO_ROOT / "Docs" / "PROBLEM_STATEMENT.md",
    "C": REPO_ROOT / "Docs" / "CONTEXT.md",
}
_SOURCE_RE = re.compile(r"^(A|IP|P|C)§([\d.]+)")


def _closed_phases() -> set[str]:
    if not CLOSE_HISTORY.exists():
        return set()
    data = json.loads(CLOSE_HISTORY.read_text(encoding="utf-8"))
    return {entry["phase"] for entry in data if entry.get("verdict") == "PASS"}


@eval_case(
    "EV-INV-15",
    proves="The phase marker can't outrun the evidence: its predecessor has a green --close run on record",
    source="EVAL.md §4.2",
    severity="MAJOR",
    tags=["invariant"],
)
def ev_inv_15():
    if not EVAL_PHASE_MARKER.exists():
        raise EvalSkip("no .claude/eval-phase marker set")
    marker = EVAL_PHASE_MARKER.read_text(encoding="utf-8").strip()
    if not marker:
        raise EvalSkip("empty .claude/eval-phase marker")
    assert marker in PHASES, f"unknown phase marker: {marker!r}"
    idx = PHASES.index(marker)
    if idx <= 1:  # P-1 or P0 has no --close prerequisite of this kind
        return
    predecessor = PHASES[idx - 1]
    closed = _closed_phases()
    assert predecessor in closed, (
        f".claude/eval-phase names {marker}, but {predecessor} has no recorded "
        f"green --close run in {CLOSE_HISTORY}"
    )


@eval_case(
    "EV-INV-16",
    proves="Any change to a chat or classification prompt forces the P5 suite to re-run",
    source="EVAL.md §6.7",
    severity="MAJOR",
    # applies_from: no classification/chat prompt exists before P3, so this
    # has a legitimate SKIP through P0-P2 — unlike a plain "invariant" tag,
    # which the runner's --close check treats as required from P0 onward.
    tags=["invariant", "applies_from:P3"],
)
def ev_inv_16():
    """Checks the discipline EV-P3-03 can't: that discipline proves the
    *mechanism* (bump the version, the cache misses) works when exercised
    deliberately; this proves nobody edited a prompt's wording *without*
    remembering to exercise it — i.e. without bumping `PROMPT_VERSION`.

    Each known prompt site reports {version, template_hash} (`classify.py`
    now; `chat.py` once P5 exists — imported defensively so this doesn't
    itself become the thing blocking P5's build). A stored hash under the
    *same* version that no longer matches the current one means the
    template changed without a version bump — a real governance failure,
    not something to silently re-baseline away. The fix is exactly what
    the eval demands: bump the version (which accepts a new baseline) or
    revert the wording.
    """
    current: dict[str, dict] = {}
    from app.pipeline import classify

    current["classify"] = classify.prompt_signature()
    try:
        from app.chat import grounding as chat_grounding  # P5 — may not exist yet
    except ImportError:
        pass
    else:
        current["chat"] = chat_grounding.prompt_signature()

    try:
        from app.fallback import llm_dom  # P7 — may not exist yet
    except ImportError:
        pass
    else:
        current["llm_dom"] = llm_dom.prompt_signature()

    if not PROMPT_SIGNATURES.exists():
        PROMPT_SIGNATURES.parent.mkdir(parents=True, exist_ok=True)
        PROMPT_SIGNATURES.write_text(json.dumps(current, indent=2), encoding="utf-8")
        return  # first time any prompt site became checkable — baseline established

    stored = json.loads(PROMPT_SIGNATURES.read_text(encoding="utf-8"))
    updated = dict(stored)
    mismatches = []
    for site, sig in current.items():
        prior = stored.get(site)
        if prior is None or prior["version"] != sig["version"]:
            updated[site] = sig  # a new site, or a legitimate version bump — accept the new baseline
            continue
        if prior["template_hash"] != sig["template_hash"]:
            mismatches.append(
                f"{site}: prompt template changed under version {sig['version']!r} without bumping "
                "its version constant — bump it (which correctly misses the cache, EV-P3-03) before this can pass"
            )
    PROMPT_SIGNATURES.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    assert not mismatches, "; ".join(mismatches)


@eval_case(
    "EV-INV-17",
    proves="Every eval's `source` reference resolves to a real section in a real doc",
    source="EVAL.md §1.2",
    severity="MINOR",
    tags=["invariant"],
)
def ev_inv_17():
    bad = []
    for ev in all_evals():
        if ev.source.startswith("EVAL.md"):
            continue  # governs the eval system itself, not the product docs
        m = _SOURCE_RE.match(ev.source)
        if not m:
            bad.append(f"{ev.id}: unparseable source {ev.source!r}")
            continue
        prefix, section = m.group(1), m.group(2)
        doc_path = _DOC_FILES.get(prefix)
        if doc_path is None or not doc_path.exists():
            bad.append(f"{ev.id}: no document for prefix {prefix!r}")
            continue
        text = doc_path.read_text(encoding="utf-8")
        top_level = section.split(".")[0]
        if not re.search(rf"^#{{1,4}}\s+{re.escape(top_level)}[.\s]", text, re.MULTILINE):
            bad.append(f"{ev.id}: {doc_path.name} has no heading for section {top_level}")
    assert not bad, f"eval sources that don't resolve to a real doc section: {bad}"
