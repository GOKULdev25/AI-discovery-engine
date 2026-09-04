"""Excel export (A§6, IP§1.3). `polars` + `xlsxwriter`. Exports the whole
project by default; `batch_id` narrows to one run — cross-batch by
default is the point of projects (A§7.2).

Sheet 1 `documents` — the frozen A§8 schema, autofiltered.
Sheet 2 `links` — per-link status and failure codes, so "fail loudly"
survives the export (P§8 criterion 2).
Sheet 3 `run_info` — project, batches, locales, extractor versions,
capture window.

Every frame below is built with an **explicit dtype schema**, never a
bare column-name list. `pl.DataFrame(rows, orient="row")` infers each
column's type from the first `infer_schema_length` (100) rows, so a
column that is null across those rows is typed `Null` and then raises
`ComputeError` on the first real value further down. That is not a
hypothetical: exporting a 62,870-document project failed on
`documents.parent_id` — null for every top-level comment, then a
YouTube reply's parent id at some row past the sample. Declaring the
types removes the inference step entirely, so a column's nullability
can never depend on row order (Docs/FEASIBILITY_LOG.md, 2026-08-31).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import xlsxwriter

from app.projects.config import ProjectConfig
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq

# Mirrors the frozen A§8 `documents` DDL field-for-field (warehouse
# migration 0001). Ordered — it drives both the SELECT and the sheet's
# column order. TIMESTAMP maps to microsecond Datetime, DOUBLE to
# Float64, everything else is text or a nullable flag.
_DOC_SCHEMA: dict[str, pl.DataType] = {
    "doc_id": pl.String,
    "project_id": pl.String,
    "batch_id": pl.String,
    "source": pl.String,
    "doc_type": pl.String,
    "source_url": pl.String,
    "subject": pl.String,
    "product_id": pl.String,
    "variant": pl.String,
    "captured_at": pl.Datetime("us"),
    "authored_at": pl.Datetime("us"),
    "author_hash": pl.String,
    "text": pl.String,
    "lang": pl.String,
    "rating": pl.Float64,
    "verified_purchase": pl.Boolean,
    "engagement": pl.String,
    "parent_id": pl.String,
    "lane": pl.String,
    "extractor_version": pl.String,
    "raw": pl.String,
}
_DOC_COLUMNS_ORDER = list(_DOC_SCHEMA)

# ops.sqlite `links` — `connector_id`, `failure_code` and `retryable` are
# all null until a link is classified or fails, which is the same
# order-dependent inference hazard as `parent_id` above.
_LINK_SCHEMA: dict[str, pl.DataType] = {
    "link_id": pl.String,
    "batch_id": pl.String,
    "url": pl.String,
    "connector_id": pl.String,
    "status": pl.String,
    "failure_code": pl.String,
    "retryable": pl.Int64,
    "doc_count": pl.Int64,
}

# ops.sqlite `batches`. `created_at` is TEXT there, not a timestamp type.
_BATCH_SCHEMA: dict[str, pl.DataType] = {
    "batch_id": pl.String,
    "status": pl.String,
    "link_count": pl.Int64,
    "created_at": pl.String,
}


async def build_export(
    resolver: ProjectResolver, project_config: ProjectConfig, batch_id: str | None = None
) -> Path:
    project_id = project_config.id
    project_dir = resolver.project_dir(project_id)

    reader = await dk.get_reader(project_dir)
    query = f"SELECT {', '.join(_DOC_COLUMNS_ORDER)} FROM documents"
    params: list[str] = []
    if batch_id:
        query += " WHERE batch_id = ?"
        params.append(batch_id)
    # Plain fetchall(), not `.pl()` — the Arrow-backed conversion `.pl()`
    # uses allocates outside DuckDB's own `memory_limit` accounting and
    # was observed to OOM under real memory pressure on this machine even
    # for a handful of rows (Docs/FEASIBILITY_LOG.md, 2026-08-29).
    # Building the frame from plain Python rows sidesteps that path
    # entirely, the same way `links_df`/`batches_df` already do below.
    doc_rows = [tuple(row) for row in reader.execute(query, params).fetchall()]
    documents_df = pl.DataFrame(doc_rows, schema=_DOC_SCHEMA, orient="row")

    async with sq.ops_db(project_dir) as ops_conn:
        links_rows = await _fetch_links(ops_conn, batch_id)
        batches_rows = await _fetch_batches(ops_conn)

    links_df = pl.DataFrame(links_rows, schema=_LINK_SCHEMA, orient="row")

    extractor_versions = sorted(
        v for v in documents_df["extractor_version"].unique().to_list() if v is not None
    ) if documents_df.height else []
    capture_min = documents_df["captured_at"].min() if documents_df.height else None
    capture_max = documents_df["captured_at"].max() if documents_df.height else None

    run_info_df = pl.DataFrame({
        "field": [
            "project_id", "project_name", "session_mode", "locales",
            "batch_filter", "document_count", "extractor_versions",
            "capture_window_start", "capture_window_end", "exported_at",
        ],
        "value": [
            project_id, project_config.name, project_config.session_mode,
            ", ".join(project_config.locales), batch_id or "(whole project)",
            str(documents_df.height), ", ".join(extractor_versions),
            str(capture_min) if capture_min else "", str(capture_max) if capture_max else "",
            datetime.now(timezone.utc).isoformat(),
        ],
    })
    batches_df = pl.DataFrame(batches_rows, schema=_BATCH_SCHEMA, orient="row")

    exports_dir = resolver.exports_dir(project_id)
    exports_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-{batch_id}" if batch_id else ""
    out_path = exports_dir / f"export{suffix}-{int(datetime.now(timezone.utc).timestamp())}.xlsx"

    workbook = xlsxwriter.Workbook(str(out_path))
    documents_df.write_excel(
        workbook=workbook, worksheet="documents",
        autofilter=True, freeze_panes=(1, 0), autofit=True,
    )
    links_df.write_excel(workbook=workbook, worksheet="links", autofilter=True, autofit=True)
    run_info_df.write_excel(workbook=workbook, worksheet="run_info", autofilter=False, autofit=True)
    batches_df.write_excel(workbook=workbook, worksheet="batches", autofilter=True, autofit=True)
    workbook.close()

    return out_path


async def _fetch_links(ops_conn, batch_id: str | None) -> list[tuple]:
    query = "SELECT id, batch_id, url, connector_id, status, failure_code, retryable, doc_count FROM links"
    args: list[str] = []
    if batch_id:
        query += " WHERE batch_id = ?"
        args.append(batch_id)
    query += " ORDER BY created_at"
    cur = await ops_conn.execute(query, args)
    rows = await cur.fetchall()
    return [tuple(r) for r in rows]


async def _fetch_batches(ops_conn) -> list[tuple]:
    cur = await ops_conn.execute(
        "SELECT id, status, link_count, created_at FROM batches ORDER BY created_at"
    )
    rows = await cur.fetchall()
    return [tuple(r) for r in rows]
