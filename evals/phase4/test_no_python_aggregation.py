"""EV-P4-08 — aggregation happens in DuckDB, not by pulling rows into
Python and reducing them there. A static scan, same discipline as
EV-INV-08's httpx grep: every `documents`/`enrichment` query in the
analytics module must do its reduction in SQL (a `GROUP BY` or an
aggregate function), and the one endpoint that *does* return raw rows
(`documents.py`) must keep them bounded by a small `LIMIT`, never an
unbounded scan.
"""

from __future__ import annotations

import re

from evals.harness import BACKEND_APP_DIR
from evals.registry import eval_case

_AGGREGATE_RE = re.compile(r"\bGROUP BY\b|\bCOUNT\s*\(|\bMIN\s*\(|\bMAX\s*\(|\bSUM\s*\(", re.IGNORECASE)


@eval_case(
    "EV-P4-08",
    proves="No analytics endpoint materializes >10k rows in Python — every query reduces in DuckDB",
    source="A§9",
    severity="MINOR",
    tags=["phase:P4"],
)
def ev_p4_08():
    analytics_path = BACKEND_APP_DIR / "api" / "analytics.py"
    text = analytics_path.read_text(encoding="utf-8")

    # Every `reader.execute(...)`/`ops_conn.execute(...)` call's SQL
    # string must contain some aggregate marker. Crude but effective:
    # split on `.execute(` and check each following chunk up to the next
    # `"""` or the parameter list for an aggregate keyword.
    calls = re.findall(r"\.execute\(\s*f?\"\"\"(.*?)\"\"\"", text, re.DOTALL)
    assert calls, "expected at least one triple-quoted SQL query in analytics.py — the scan pattern may be stale"
    unaggregated = [sql[:80] for sql in calls if not _AGGREGATE_RE.search(sql)]
    assert not unaggregated, f"queries with no GROUP BY/aggregate found in analytics.py: {unaggregated}"

    documents_path = BACKEND_APP_DIR / "api" / "documents.py"
    doc_text = documents_path.read_text(encoding="utf-8")
    assert "_MAX_LIMIT" in doc_text and re.search(r"_MAX_LIMIT\s*=\s*\d+", doc_text), (
        "documents.py must cap its page size with a small constant, not allow an unbounded LIMIT"
    )
    max_limit = int(re.search(r"_MAX_LIMIT\s*=\s*(\d+)", doc_text).group(1))
    assert max_limit <= 10_000, f"documents.py's page-size cap ({max_limit}) exceeds the 10k row budget"
