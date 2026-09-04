"""EV-P0-16 — the eval harness can discover, tag-filter, and report
(EVAL.md §3.2). `scripts/eval.py` is a Phase 0 deliverable and its own
first customer."""

from __future__ import annotations

import json
import subprocess
import sys

from evals.harness import REPO_ROOT
from evals.registry import eval_case


@eval_case(
    "EV-P0-16",
    proves="eval.py discovers registered IDs, filters by tag/id, and emits valid latest.json",
    source="EVAL.md §3.2",
    severity="MAJOR",
    tags=["phase:P0"],
)
def ev_p0_16():
    from evals.registry import all_evals

    known = {ev.id for ev in all_evals()}
    assert "EV-P0-01" in known and "EV-INV-02" in known, "registry did not discover expected evals"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "eval.py"), "--id", "EV-P0-01"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"eval.py --id EV-P0-01 exited {result.returncode}: {result.stderr}"

    report_path = REPO_ROOT / "evals" / "reports" / "latest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report) >= {"phase", "totals", "phase_verdict", "blocking", "results"}
    ids_in_report = {r["id"] for r in report["results"]}
    assert ids_in_report == {"EV-P0-01"}, f"--id filtering ran more than requested: {ids_in_report}"
