#!/usr/bin/env python
"""The eval runner (EVAL.md §3.2). Discovers evals, filters by tag, writes
evals/reports/latest.json and latest.md, and speaks --hook-json for the
automatic Stop-hook trigger.

Exit codes: 0 clear · 1 blocking failures · 2 harness unrunnable · 3
non-blocking failures only.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import inspect
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PHASES = ["P-1", "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"]
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
CLOSE_HISTORY = REPORTS_DIR / "close_history.json"

_PHASE_MODULE = {
    "P-1": "evals.phase_minus1",
    "P0": "evals.phase0",
    "P1": "evals.phase1",
    "P2": "evals.phase2",
    "P3": "evals.phase3",
    "P4": "evals.phase4",
    "P5": "evals.phase5",
    "P6": "evals.phase6",
    "P7": "evals.phase7",
}


def _import_suites(target_phase: str | None) -> None:
    import importlib

    importlib.import_module("evals.invariants")
    if target_phase is None:
        for mod in _PHASE_MODULE.values():
            _try_import(mod)
        return
    idx = PHASES.index(target_phase)
    for phase in PHASES[: idx + 1]:
        _try_import(_PHASE_MODULE[phase])


def _try_import(mod_name: str) -> None:
    import importlib

    try:
        importlib.import_module(mod_name)
    except ModuleNotFoundError:
        pass  # that phase's suite doesn't exist yet — nothing to run


def _applies_now(tags: list[str], target_phase: str | None) -> bool:
    """An `applies_from:PN` tag gives an invariant a legitimate SKIP window
    before PN (e.g. EV-INV-16 can't apply before a prompt exists in P3) —
    without one, an invariant is expected to hold from P0 onward, so a
    SKIP during --close is illegitimate (EVAL.md §1.3)."""
    for t in tags:
        if t.startswith("applies_from:"):
            required_phase = t.split(":", 1)[1]
            if target_phase is None:
                return True
            return PHASES.index(target_phase) >= PHASES.index(required_phase)
    return True


EVAL_TIMEOUT_S = 30
# "slow" evals are already opted out of every non-`--close`/`--id` run
# (see `_included` below) precisely because they do real-scale work (e.g.
# EV-P4-03 seeding 100k rows) — the same 30s budget that catches a hang
# in an ordinary eval would make a legitimately-slow one flake on
# nothing but machine load. Generous rather than tight, since a "slow"
# eval hanging for real is still caught, just later.
SLOW_EVAL_TIMEOUT_S = 120


async def _run_async_with_timeout(fn, timeout: float) -> None:
    await asyncio.wait_for(fn(), timeout=timeout)


def _run_one(fn, tags: list[str] | None = None) -> tuple[str, str | None]:
    """Returns (verdict, detail)."""
    from evals.registry import EvalSkip

    timeout = SLOW_EVAL_TIMEOUT_S if tags and "slow" in tags else EVAL_TIMEOUT_S
    try:
        if inspect.iscoroutinefunction(fn):
            asyncio.run(_run_async_with_timeout(fn, timeout))
        else:
            fn()
        return "PASS", None
    except EvalSkip as exc:
        return "SKIP", str(exc)
    except AssertionError as exc:
        return "FAIL", str(exc) or "assertion failed"
    except asyncio.TimeoutError:
        return "BLOCKED", f"exceeded the {timeout}s per-eval timeout — likely a hang"
    except Exception as exc:  # the eval itself is broken, not the product
        return "BLOCKED", f"{type(exc).__name__}: {exc}"
    finally:
        # Each eval opens and closes its own temp-project DuckDB/SQLite
        # connections; without a forced collection between evals, C-level
        # buffers from a just-closed connection can outlive it long enough
        # to compound across a long sequential run, which is what turned
        # an isolated PASS into an OOM only when run as part of the full
        # suite (observed under real memory pressure on this machine).
        gc.collect()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--id", dest="eval_id")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--hook-json", action="store_true")
    parser.add_argument("--last-signature", default="")
    parser.add_argument("--signature-out")
    args = parser.parse_args()

    try:
        _import_suites(args.phase)
        from evals.registry import all_evals, get
    except Exception as exc:
        print(json.dumps({"error": f"harness unrunnable: {exc}"}))
        return 2

    if args.eval_id:
        target = get(args.eval_id)
        if target is None:
            print(json.dumps({"error": f"unknown eval id {args.eval_id}"}))
            return 2
        candidates = [target]
    else:
        candidates = all_evals()
        allowed_phases = None
        if args.phase:
            idx = PHASES.index(args.phase)
            allowed_phases = set(PHASES[: idx + 1])

        def _included(ev) -> bool:
            if "live" in ev.tags and not args.live:
                return False
            if "slow" in ev.tags and not args.close:
                return False
            if ev.tags == ["invariant"] or "invariant" in ev.tags:
                return True
            phase_tag = ev.phase_tag()
            if allowed_phases is not None and phase_tag is not None:
                return phase_tag in allowed_phases
            return True

        candidates = [ev for ev in candidates if _included(ev)]

    results = []
    started = time.time()
    verbose = not args.hook_json
    for ev in candidates:
        if verbose:
            print(f"... {ev.id}", end=" ", flush=True, file=sys.stderr)
        t0 = time.time()
        verdict, detail = _run_one(ev.fn, ev.tags)
        dt = round(time.time() - t0, 3)
        if verbose:
            print(f"{verdict} ({dt}s)", file=sys.stderr)
        results.append({
            "id": ev.id, "verdict": verdict, "severity": ev.severity,
            "proves": ev.proves, "detail": detail, "duration_s": dt, "tags": ev.tags,
        })

    duration = round(time.time() - started, 2)
    totals = {"pass": 0, "fail": 0, "skip": 0, "blocked": 0}
    blocking = []
    for r in results:
        totals[r["verdict"].lower()] += 1
        is_illegitimate_skip = (
            r["verdict"] == "SKIP" and args.close and _applies_now(r["tags"], args.phase)
        )
        if r["verdict"] in ("FAIL", "BLOCKED") and r["severity"] in ("BLOCKER", "MAJOR"):
            blocking.append(r["id"])
        elif is_illegitimate_skip and r["severity"] in ("BLOCKER", "MAJOR"):
            r["verdict"] = "FAIL"
            r["detail"] = (r["detail"] or "") + " [SKIP after owning phase's --close run counts as FAIL]"
            totals["skip"] -= 1
            totals["fail"] += 1
            blocking.append(r["id"])

    phase_verdict = "FAIL" if blocking else "PASS"
    report = {
        "phase": args.phase, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "duration_s": duration, "totals": totals, "phase_verdict": phase_verdict,
        "blocking": blocking, "results": results,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (REPORTS_DIR / "latest.md").write_text(_render_markdown(report), encoding="utf-8")

    if args.close and phase_verdict == "PASS" and args.phase:
        _record_close(args.phase)

    if args.hook_json:
        print(_render_hook_json(report, args.last_signature, args.signature_out))

    # Phase 6 evals can start a real Playwright driver process
    # (`app.browser.session`). Nothing else in this script's lifetime
    # stops it, and an unstopped driver process can hang the interpreter
    # at exit (observed live: a bare `python scripts/eval.py --id
    # EV-P6-07` hung well past its own 30s per-eval timeout). Safe to
    # call unconditionally — a no-op if the browser module was never
    # touched this run.
    try:
        from app.browser import session as browser_session

        asyncio.run(browser_session.close_all())
    except ImportError:
        pass

    if blocking:
        return 1
    if totals["fail"] or totals["blocked"]:
        return 3
    return 0


def _render_markdown(report: dict) -> str:
    lines = [f"# Eval report — phase {report['phase']}", "", f"Verdict: **{report['phase_verdict']}**", ""]
    lines.append("| ID | Verdict | Severity | Proves |")
    lines.append("|---|---|---|---|")
    for r in report["results"]:
        lines.append(f"| {r['id']} | {r['verdict']} | {r['severity']} | {r['proves']} |")
    failures = [r for r in report["results"] if r["verdict"] in ("FAIL", "BLOCKED")]
    if failures:
        lines.append("")
        lines.append("## Failures")
        for r in failures:
            lines.append(f"- **{r['id']}** ({r['severity']}): {r['detail']}")
    return "\n".join(lines) + "\n"


def _render_hook_json(report: dict, last_signature: str, signature_out: str | None) -> str:
    blocking = sorted(report["blocking"])
    signature = hashlib.sha256(",".join(blocking).encode()).hexdigest()[:16] if blocking else ""
    if signature_out:
        Path(signature_out).write_text(signature, encoding="utf-8")

    if not blocking:
        n = report["totals"]["pass"]
        return json.dumps({"systemMessage": f"EV ✓ {report['phase']} · {n} passed"})

    if signature == last_signature and last_signature:
        return json.dumps({
            "systemMessage": f"EV ⚠ {report['phase']}: same failures as last turn ({', '.join(blocking)}) — not re-blocking"
        })

    lines = [f"Eval suite failed for phase {report['phase']}:"]
    for r in report["results"]:
        if r["id"] in blocking:
            lines.append(f"- {r['id']} ({r['severity']}): {r['proves']} — {r['detail']}")
    return json.dumps({"decision": "block", "reason": "\n".join(lines)})


def _record_close(phase: str) -> None:
    history = []
    if CLOSE_HISTORY.exists():
        history = json.loads(CLOSE_HISTORY.read_text(encoding="utf-8"))
    history.append({"phase": phase, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "verdict": "PASS"})
    CLOSE_HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
