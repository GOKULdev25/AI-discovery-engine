"""`GET /projects/{p}/documents` (A§13) — paged and filterable **across all
batches**: cross-batch by default is the single biggest reason projects
exist rather than a `tag` column (A§7.2).

Keyset pagination on `(captured_at, doc_id)`, never `OFFSET` — an offset
shifts under concurrent inserts (a batch finishing mid-page would skip or
duplicate rows across pages); a keyset cursor only ever moves forward
past rows already seen, so it's stable regardless of what else the
warehouse's single writer commits in between (EV-P4-09).
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import settings_dep
from app.config import Settings
from app.projects.resolver import get_resolver
from app.store import duckdb as dk

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


class DocumentRow(BaseModel):
    doc_id: str
    source: str
    doc_type: str
    source_url: str
    subject: str | None
    captured_at: str | None
    authored_at: str | None
    text: str | None
    lang: str | None
    rating: float | None
    verified_purchase: bool | None
    sentiment_prior: float | None
    gate_band: str | None
    # Provenance is never optional (A§8), and a Lane 3 row is explicitly
    # lower-confidence than a Lane 1 one — IP§7.1 requires that be *shown*,
    # not just stored. The export already carried it; this is what lets the
    # UI carry it too.
    lane: str | None = None
    extractor_version: str | None = None
    # Captured by the connectors since P1 but exposed nowhere until now, so
    # an App Store review lost its title, a Reddit comment its thread, and
    # every source its like/upvote count. `engagement` is the source's own
    # raw blob; `engagement_count`/`engagement_kind` are the normalized
    # pair from `0003_engagement.sql` — the kind always travels with the
    # number, because these are not one quantity across sources.
    product_id: str | None = None
    variant: str | None = None
    parent_id: str | None = None
    engagement: dict | None = None
    engagement_count: int | None = None
    engagement_kind: str | None = None


class DocumentsResponse(BaseModel):
    documents: list[DocumentRow]
    next_cursor: str | None


def _decode_engagement(raw: object) -> dict | None:
    """`documents.engagement` is stored JSON-encoded. A blob that doesn't
    parse returns None rather than raising — a malformed engagement value
    is not a reason to fail the whole page of documents, and a null here
    reads correctly as "not captured"."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _encode_cursor(captured_at: str, doc_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([captured_at, doc_id]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        captured_at, doc_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return captured_at, doc_id
    except Exception as exc:
        raise HTTPException(422, "invalid cursor") from exc


@router.get("", response_model=DocumentsResponse)
async def list_documents(
    project_id: str,
    batch_id: str | None = None,
    source: str | None = None,
    gate_band: str | None = None,
    doc_type: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=_DEFAULT_LIMIT, le=_MAX_LIMIT, gt=0),
    settings: Settings = Depends(settings_dep),
):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)

    where = ["d.project_id = ?"]
    params: list[object] = [project_id]
    if batch_id:
        where.append("d.batch_id = ?")
        params.append(batch_id)
    if source:
        where.append("d.source = ?")
        params.append(source)
    if gate_band:
        where.append("e.gate_band = ?")
        params.append(gate_band)
    if doc_type:
        where.append("d.doc_type = ?")
        params.append(doc_type)
    if q and q.strip():
        # A plain substring match against the text and title, not the FTS5
        # index: that index lives in the project's ops.sqlite while these
        # rows live in DuckDB, and joining across two database files to
        # serve a filter would cost more than it saves. DuckDB scans this
        # columnar, and the page stays capped by `_MAX_LIMIT` either way.
        where.append("(lower(d.text) LIKE ? OR lower(COALESCE(d.subject, '')) LIKE ?)")
        needle = f"%{q.strip().lower()}%"
        params.extend([needle, needle])
    if cursor:
        captured_at, doc_id = _decode_cursor(cursor)
        where.append("(d.captured_at, d.doc_id) < (CAST(? AS TIMESTAMP), ?)")
        params.extend([captured_at, doc_id])

    sql = f"""
        SELECT d.doc_id, d.source, d.doc_type, d.source_url, d.subject, d.captured_at,
               d.authored_at, d.text, d.lang, d.rating, d.verified_purchase,
               e.sentiment_prior, e.gate_band, d.lane, d.extractor_version,
               d.product_id, d.variant, d.parent_id, d.engagement,
               e.engagement_count, e.engagement_kind
        FROM documents d
        LEFT JOIN enrichment e ON d.doc_id = e.doc_id
        WHERE {" AND ".join(where)}
        ORDER BY d.captured_at DESC, d.doc_id DESC
        LIMIT ?
    """
    rows = reader.execute(sql, params + [limit]).fetchall()
    columns = [c[0] for c in reader.description]
    documents = [dict(zip(columns, row)) for row in rows]
    for doc in documents:
        doc["captured_at"] = str(doc["captured_at"]) if doc["captured_at"] is not None else None
        doc["authored_at"] = str(doc["authored_at"]) if doc["authored_at"] is not None else None
        doc["engagement"] = _decode_engagement(doc.get("engagement"))

    next_cursor = None
    if len(documents) == limit:
        last = documents[-1]
        next_cursor = _encode_cursor(last["captured_at"], last["doc_id"])

    return {"documents": documents, "next_cursor": next_cursor}


@router.get("/{doc_id}", response_model=DocumentRow)
async def get_document(project_id: str, doc_id: str, settings: Settings = Depends(settings_dep)):
    """One document by id — what a chat citation's doc_id links to."""
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    row = reader.execute(
        """SELECT d.doc_id, d.source, d.doc_type, d.source_url, d.subject, d.captured_at,
                  d.authored_at, d.text, d.lang, d.rating, d.verified_purchase,
                  e.sentiment_prior, e.gate_band, d.lane, d.extractor_version,
                  d.product_id, d.variant, d.parent_id, d.engagement,
                  e.engagement_count, e.engagement_kind
           FROM documents d LEFT JOIN enrichment e ON d.doc_id = e.doc_id
           WHERE d.project_id = ? AND d.doc_id = ?""",
        [project_id, doc_id],
    ).fetchone()
    if row is None:
        raise HTTPException(404, "document not found")
    columns = [c[0] for c in reader.description]
    doc = dict(zip(columns, row))
    doc["captured_at"] = str(doc["captured_at"]) if doc["captured_at"] is not None else None
    doc["authored_at"] = str(doc["authored_at"]) if doc["authored_at"] is not None else None
    doc["engagement"] = _decode_engagement(doc.get("engagement"))
    return doc
