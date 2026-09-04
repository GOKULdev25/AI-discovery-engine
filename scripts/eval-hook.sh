#!/usr/bin/env bash
# eval-hook.sh — automatic phase-eval trigger (Docs/EVAL.md §4)
#
# Wired as a Claude Code `Stop` hook: runs the eval suite for the phase named
# in .claude/eval-phase after every implementation turn.
#
# Contract:
#   - Emits hook JSON on stdout (produced by scripts/eval.py) or nothing.
#   - ALWAYS exits 0. The decision travels in the JSON, never in the exit code,
#     so a harness problem can never wedge a session.
#   - Silent no-op until the eval harness exists, so it is safe to install now.
#
# Disable for a turn:  EVAL_HOOK_DISABLE=1
# Disable entirely:    empty or remove .claude/eval-phase

set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$ROOT" 2>/dev/null || exit 0

# --- escape hatches -----------------------------------------------------------
[ "${EVAL_HOOK_DISABLE:-0}" = "1" ] && exit 0

PHASE_FILE=".claude/eval-phase"
[ -f "$PHASE_FILE" ] || exit 0
PHASE="$(tr -d '[:space:]' < "$PHASE_FILE" 2>/dev/null)"
[ -n "$PHASE" ] || exit 0

# --- harness present? ---------------------------------------------------------
# Before Phase 0 builds scripts/eval.py this hook costs nothing and says nothing.
RUNNER="scripts/eval.py"
[ -f "$RUNNER" ] || exit 0

# Probe by execution, not by PATH lookup: on Windows `python` often resolves to
# the Microsoft Store alias stub, which is on PATH but is not an interpreter.
PY=""
for c in python3 python py; do
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c "" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || exit 0

# --- loop guard ---------------------------------------------------------------
# eval.py compares the current failure signature with the last one it blocked on.
# Identical signature => it reports a warning instead of blocking again, so an
# eval that genuinely cannot pass yet can never trap the session in a loop.
SIG_FILE=".claude/.eval-signature"
LAST_SIG=""
[ -f "$SIG_FILE" ] && LAST_SIG="$(tr -d '[:space:]' < "$SIG_FILE" 2>/dev/null)"

OUT="$("$PY" "$RUNNER" \
        --phase "$PHASE" \
        --hook-json \
        --last-signature "$LAST_SIG" \
        --signature-out "$SIG_FILE" 2>/dev/null)"

# Anything on stdout is the hook's JSON response; silence means "nothing to say".
[ -n "$OUT" ] && printf '%s\n' "$OUT"

exit 0
