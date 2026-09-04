"""Connector output → the A§8 row shape (IP§2.1). Applied to every row in
`Ctx.emit()` before it reaches staging, so Lane 3's messier output
(Phase 7, LLM-DOM) gets the same guarantees Lane 1's well-typed
connectors already happen to provide — one place, not one per connector.

Null stays null; there is no `or captured_at` anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.pipeline.ids import normalize_text_for_id

_VALID_DOC_TYPES = {"review", "comment", "post", "qa_question", "qa_answer"}


def normalize_row(row: dict) -> dict:
    row = dict(row)
    row["captured_at"] = _to_utc_iso(row.get("captured_at"), field="captured_at", required=True)
    row["authored_at"] = _to_utc_iso(row.get("authored_at"), field="authored_at", required=False)
    if row.get("text") is not None:
        row["text"] = normalize_text_for_id(row["text"])
    if row.get("doc_type") not in _VALID_DOC_TYPES:
        raise ValueError(f"invalid doc_type: {row.get('doc_type')!r}")
    if not row.get("lane") or not row.get("extractor_version"):
        raise ValueError("lane and extractor_version are never optional (A§8)")
    return row


def _to_utc_iso(value, *, field: str, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required and must never be inferred (P§6)")
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        # Already a string — trust it if it parses as a real timestamp,
        # rather than silently passing through garbage.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    raise TypeError(f"{field} must be a datetime or ISO string, got {type(value)}")
