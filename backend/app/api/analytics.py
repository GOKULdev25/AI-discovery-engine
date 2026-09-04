"""Dashboard aggregation endpoints (A§13, IP§4). Every number here is a
DuckDB `GROUP BY`/aggregate — nothing pulls raw rows into Python and sums
them (EV-P4-08), so a project's whole history aggregates in the time a
columnar scan takes, not the time an ORM would (A§9).

Every response carries a `meta` block (document count, sources, capture
window) as the chart's denominator caption (IP§4) — a chart is never
shown without saying what it's a chart *of*. And `document_count == 0`
is a real, structurally distinct answer (empty `data`, `meta.document_count:
0`), never a zeroed chart that could be misread as a finding (EV-P4-07).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import settings_dep
from app.config import Settings
from app.projects.resolver import get_resolver
from app.sources.profiles import get_profile
from app.store import duckdb as dk
from app.store import sqlite as sq

router = APIRouter(prefix="/projects/{project_id}/analytics", tags=["analytics"])

# A standard-enough list to strip filler words from "top themes" — kept
# short and boring on purpose (IP§4 doesn't ask for anything smarter than
# word frequency, and this is the "cheapest phase in the plan").
_STOPWORDS = [
    "the", "and", "for", "that", "this", "with", "have", "has", "had",
    "was", "were", "are", "you", "your", "but", "not", "all", "can",
    "its", "it's", "just", "very", "really", "app", "get", "got", "use",
    "using", "used", "will", "would", "could", "about", "when", "what",
    "they", "them", "their", "there", "then", "than", "into", "out",
    "some", "more", "most", "much", "also", "one", "now", "even",
]


class Meta(BaseModel):
    document_count: int
    sources: list[str]
    mixed_source: bool
    captured_from: str | None
    captured_to: str | None


class NamedCount(BaseModel):
    name: str
    doc_count: int


class RatingBucket(BaseModel):
    rating: float
    doc_count: int


class EngagementBlock(BaseModel):
    """Engagement for ONE source only.

    `kind` is the source's own word for the metric — `likes`, `score`,
    `helpful`. It is mandatory here, and there is deliberately no
    cross-source engagement endpoint: a YouTube like and a Reddit upvote
    are different populations with different mechanics, so summing them
    would be the fabrication-by-aggregation IP§P4 warns about.
    """

    kind: str
    label: str
    covered: int  # documents that actually carry a value
    total: int
    max: int
    mean: float
    buckets: list[NamedCount]


class SourceBlock(BaseModel):
    source: str
    label: str
    doc_count: int
    captured_from: str | None
    captured_to: str | None
    doc_types: list[NamedCount]
    volume: list[NamedCount]  # name = day
    lanes: list[NamedCount]
    languages: list[NamedCount]
    sentiment_prior_breakdown: list[NamedCount]
    # Present only when this source's profile declares ratings AND at
    # least one row carries one. `rating_coverage` states the denominator
    # so "0 of 349 have a rating" is visible rather than an empty chart.
    ratings: list[RatingBucket]
    rating_coverage: int
    rating_scale: float | None
    engagement: EngagementBlock | None


class BySourceResponse(BaseModel):
    meta: Meta
    sources: list[SourceBlock]


class VolumePoint(BaseModel):
    day: str
    source: str
    doc_count: int


class VolumeResponse(BaseModel):
    meta: Meta
    data: list[VolumePoint]


class SourceCount(BaseModel):
    source: str
    doc_count: int


class SourcesResponse(BaseModel):
    meta: Meta
    data: list[SourceCount]


class SentimentBucket(BaseModel):
    source: str
    bucket: str
    doc_count: int


class SentimentResponse(BaseModel):
    meta: Meta
    sentiment_prior_breakdown: list[SentimentBucket]


class RatingCount(BaseModel):
    source: str
    rating: float
    doc_count: int


class RatingsResponse(BaseModel):
    meta: Meta
    data: list[RatingCount]


class ThemeCount(BaseModel):
    term: str
    freq: int


class ThemesResponse(BaseModel):
    meta: Meta
    data: list[ThemeCount]


class FailureCount(BaseModel):
    failure_code: str
    count: int


class FailuresResponse(BaseModel):
    total_links: int
    data: list[FailureCount]


def _where(
    project_id: str, batch_id: str | None, source: str | None = None
) -> tuple[str, list[object]]:
    clause = "project_id = ?"
    params: list[object] = [project_id]
    if batch_id:
        clause += " AND batch_id = ?"
        params.append(batch_id)
    if source:
        clause += " AND source = ?"
        params.append(source)
    return clause, params


def _where_on(
    alias: str, project_id: str, batch_id: str | None, source: str | None = None
) -> tuple[str, list[object]]:
    """Same predicate, but every column qualified with a table alias.

    The older joined queries interpolate `_where`'s output after a bare
    `d.`, which only qualifies the *first* column and leaves the rest
    unqualified — harmless today because only `documents` has those
    columns, but it breaks the moment a joined table shares a name.
    New joined queries use this instead."""
    clause = f"{alias}.project_id = ?"
    params: list[object] = [project_id]
    if batch_id:
        clause += f" AND {alias}.batch_id = ?"
        params.append(batch_id)
    if source:
        clause += f" AND {alias}.source = ?"
        params.append(source)
    return clause, params


def _meta(
    reader, project_id: str, batch_id: str | None, source: str | None = None
) -> Meta:
    clause, params = _where(project_id, batch_id, source)
    row = reader.execute(
        f"SELECT COUNT(*), MIN(captured_at), MAX(captured_at) FROM documents WHERE {clause}", params
    ).fetchone()
    sources = [
        r[0] for r in reader.execute(f"SELECT DISTINCT source FROM documents WHERE {clause}", params).fetchall()
    ]
    return Meta(
        document_count=row[0],
        sources=sorted(sources),
        mixed_source=len(sources) > 1,
        captured_from=str(row[1]) if row[1] is not None else None,
        captured_to=str(row[2]) if row[2] is not None else None,
    )


@router.get("/volume", response_model=VolumeResponse)
async def volume(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    """Documents captured per day, broken down by source (never merged
    into one undifferentiated line — EV-P4-04)."""
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    clause, params = _where(project_id, batch_id)
    rows = reader.execute(
        f"""SELECT CAST(date_trunc('day', captured_at) AS VARCHAR) AS day, source, COUNT(*) AS doc_count
            FROM documents WHERE {clause} GROUP BY 1, 2 ORDER BY 1""",
        params,
    ).fetchall()
    return {
        "meta": _meta(reader, project_id, batch_id),
        "data": [{"day": r[0], "source": r[1], "doc_count": r[2]} for r in rows],
    }


@router.get("/sources", response_model=SourcesResponse)
async def sources(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    clause, params = _where(project_id, batch_id)
    rows = reader.execute(
        f"SELECT source, COUNT(*) AS doc_count FROM documents WHERE {clause} GROUP BY 1 ORDER BY 2 DESC", params
    ).fetchall()
    return {
        "meta": _meta(reader, project_id, batch_id),
        "data": [{"source": r[0], "doc_count": r[1]} for r in rows],
    }


@router.get("/sentiment", response_model=SentimentResponse)
async def sentiment(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    """The lexicon *prior* only (VADER, Phase 2 local enrichment) —
    structurally its own field (`sentiment_prior_breakdown`), never a
    generic "sentiment" name, so a future LLM-derived label can never be
    silently merged into this chart (EV-P4-05, A§11.2)."""
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    clause, params = _where(project_id, batch_id)
    # VADER's own documented compound-score thresholds — not an
    # arbitrary cut this codebase invented.
    rows = reader.execute(
        f"""SELECT d.source,
                   CASE WHEN e.sentiment_prior IS NULL THEN 'unknown'
                        WHEN e.sentiment_prior >= 0.05 THEN 'positive'
                        WHEN e.sentiment_prior <= -0.05 THEN 'negative'
                        ELSE 'neutral' END AS bucket,
                   COUNT(*) AS doc_count
            FROM documents d LEFT JOIN enrichment e ON d.doc_id = e.doc_id
            WHERE d.{clause}
            GROUP BY 1, 2""",
        params,
    ).fetchall()
    return {
        "meta": _meta(reader, project_id, batch_id),
        "sentiment_prior_breakdown": [{"source": r[0], "bucket": r[1], "doc_count": r[2]} for r in rows],
    }


@router.get("/ratings", response_model=RatingsResponse)
async def ratings(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    clause, params = _where(project_id, batch_id)
    rows = reader.execute(
        f"""SELECT source, rating, COUNT(*) AS doc_count FROM documents
            WHERE {clause} AND rating IS NOT NULL GROUP BY 1, 2 ORDER BY 2""",
        params,
    ).fetchall()
    return {
        "meta": _meta(reader, project_id, batch_id),
        "data": [{"source": r[0], "rating": r[1], "doc_count": r[2]} for r in rows],
    }


@router.get("/themes", response_model=ThemesResponse)
async def themes(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    """Top terms by raw frequency — a cheap, local, zero-AI-cost signal
    (IP§4's "top themes"), computed entirely in DuckDB."""
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    clause, params = _where(project_id, batch_id)
    placeholders = ", ".join("?" for _ in _STOPWORDS)
    rows = reader.execute(
        f"""SELECT word, COUNT(*) AS freq FROM (
                SELECT UNNEST(string_split(lower(regexp_replace(text, '[^a-zA-Z0-9'' ]', ' ', 'g')), ' ')) AS word
                FROM documents WHERE {clause} AND text IS NOT NULL
            )
            WHERE length(word) > 3 AND word NOT IN ({placeholders})
            GROUP BY word ORDER BY freq DESC LIMIT 20""",
        params + _STOPWORDS,
    ).fetchall()
    return {
        "meta": _meta(reader, project_id, batch_id),
        "data": [{"term": r[0], "freq": r[1]} for r in rows],
    }


@router.get("/failures", response_model=FailuresResponse)
async def failures(project_id: str, batch_id: str | None = None, settings: Settings = Depends(settings_dep)):
    """From `ops.sqlite` (A§8.1 taxonomy lives on `links`, not the
    warehouse) — a summary of what didn't extract, alongside what did."""
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    batch_filter = " AND batch_id = ?" if batch_id else ""
    batch_params: list[object] = [batch_id] if batch_id else []
    async with sq.ops_db(project_dir) as ops_conn:
        cur = await ops_conn.execute(
            f"SELECT failure_code, COUNT(*) c FROM links WHERE failure_code IS NOT NULL{batch_filter} "
            f"GROUP BY failure_code ORDER BY c DESC",
            batch_params,
        )
        rows = await cur.fetchall()
        cur = await ops_conn.execute(f"SELECT COUNT(*) c FROM links WHERE 1=1{batch_filter}", batch_params)
        total_row = await cur.fetchone()
    return {
        "total_links": total_row["c"] if total_row else 0,
        "data": [{"failure_code": r["failure_code"], "count": r["c"]} for r in rows],
    }


_ENGAGEMENT_BUCKET_SQL = """CASE
    WHEN e.engagement_count IS NULL THEN 'none'
    WHEN e.engagement_count = 0 THEN '0'
    WHEN e.engagement_count <= 2 THEN '1-2'
    WHEN e.engagement_count <= 10 THEN '3-10'
    WHEN e.engagement_count <= 50 THEN '11-50'
    WHEN e.engagement_count <= 200 THEN '51-200'
    ELSE '200+' END"""

_ENGAGEMENT_BUCKET_ORDER = ["0", "1-2", "3-10", "11-50", "51-200", "200+"]


@router.get("/by-source", response_model=BySourceResponse)
async def by_source(
    project_id: str,
    batch_id: str | None = None,
    settings: Settings = Depends(settings_dep),
):
    """One block per source, carrying only the dimensions that source
    actually provides (`app/sources/profiles.py`).

    This exists because a single chart across sources is ambiguous by
    construction: App Store rows have a 5-star rating and an app version,
    YouTube rows have neither but have a like count and thread via
    `parent_id`. Drawing one rating axis over both produced a near-empty
    chart, and — where two rating-bearing sources were present — silently
    overlapping x-values. A§12's "not directly comparable" rule, applied
    to chart *selection* rather than just to labelling (EV-P4-04).

    Ratings and engagement appear here and are deliberately absent from
    any all-sources view.
    """
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    reader = await dk.get_reader(project_dir)
    clause, params = _where(project_id, batch_id)
    jclause, jparams = _where_on("d", project_id, batch_id)

    totals = reader.execute(
        f"""SELECT source, COUNT(*) AS doc_count, MIN(captured_at), MAX(captured_at)
            FROM documents WHERE {clause} GROUP BY 1 ORDER BY 2 DESC""",
        params,
    ).fetchall()

    doc_types = reader.execute(
        f"SELECT source, doc_type, COUNT(*) AS doc_count FROM documents WHERE {clause} GROUP BY 1, 2 ORDER BY 3 DESC",
        params,
    ).fetchall()

    volume = reader.execute(
        f"""SELECT source, CAST(date_trunc('day', captured_at) AS VARCHAR) AS day, COUNT(*) AS doc_count
            FROM documents WHERE {clause} GROUP BY 1, 2 ORDER BY 2""",
        params,
    ).fetchall()

    lanes = reader.execute(
        f"SELECT source, lane, COUNT(*) AS doc_count FROM documents WHERE {clause} GROUP BY 1, 2 ORDER BY 3 DESC",
        params,
    ).fetchall()

    languages = reader.execute(
        f"""SELECT source, COALESCE(lang, 'unknown') AS lang, COUNT(*) AS doc_count
            FROM documents WHERE {clause} GROUP BY 1, 2 ORDER BY 3 DESC""",
        params,
    ).fetchall()

    ratings = reader.execute(
        f"""SELECT source, rating, COUNT(*) AS doc_count FROM documents
            WHERE {clause} AND rating IS NOT NULL GROUP BY 1, 2 ORDER BY 2""",
        params,
    ).fetchall()

    rating_cov = reader.execute(
        f"SELECT source, COUNT(rating) AS covered FROM documents WHERE {clause} GROUP BY 1",
        params,
    ).fetchall()

    sentiment = reader.execute(
        f"""SELECT d.source,
                   CASE WHEN e.sentiment_prior IS NULL THEN 'unknown'
                        WHEN e.sentiment_prior >= 0.05 THEN 'positive'
                        WHEN e.sentiment_prior <= -0.05 THEN 'negative'
                        ELSE 'neutral' END AS bucket,
                   COUNT(*) AS doc_count
            FROM documents d LEFT JOIN enrichment e ON d.doc_id = e.doc_id
            WHERE {jclause} GROUP BY 1, 2""",
        jparams,
    ).fetchall()

    eng_stats = reader.execute(
        f"""SELECT d.source, e.engagement_kind,
                   COUNT(e.engagement_count) AS covered,
                   COALESCE(SUM(e.engagement_count), 0) AS total,
                   COALESCE(MAX(e.engagement_count), 0) AS max_value,
                   COALESCE(AVG(e.engagement_count), 0) AS mean_value
            FROM documents d LEFT JOIN enrichment e ON d.doc_id = e.doc_id
            WHERE {jclause} AND e.engagement_kind IS NOT NULL
            GROUP BY 1, 2""",
        jparams,
    ).fetchall()

    eng_buckets = reader.execute(
        f"""SELECT d.source, {_ENGAGEMENT_BUCKET_SQL} AS bucket, COUNT(*) AS doc_count
            FROM documents d LEFT JOIN enrichment e ON d.doc_id = e.doc_id
            WHERE {jclause} AND e.engagement_kind IS NOT NULL
            GROUP BY 1, 2""",
        jparams,
    ).fetchall()

    def by_src(rows, key_index: int = 1, count_index: int = 2):
        out: dict[str, list[NamedCount]] = {}
        for r in rows:
            out.setdefault(r[0], []).append(
                NamedCount(name=str(r[key_index]), doc_count=r[count_index])
            )
        return out

    types_map = by_src(doc_types)
    volume_map = by_src(volume)
    lanes_map = by_src(lanes)
    langs_map = by_src(languages)
    sentiment_map = by_src(sentiment)
    buckets_map = by_src(eng_buckets)
    cov_map = {r[0]: r[1] for r in rating_cov}
    stats_map = {r[0]: r for r in eng_stats}

    ratings_map: dict[str, list[RatingBucket]] = {}
    for r in ratings:
        ratings_map.setdefault(r[0], []).append(
            RatingBucket(rating=float(r[1]), doc_count=r[2])
        )

    blocks: list[SourceBlock] = []
    for source, doc_count, first, last in totals:
        profile = get_profile(source)
        stats = stats_map.get(source)
        engagement = None
        if stats is not None and profile.engagement is not None:
            ordered = {b.name: b.doc_count for b in buckets_map.get(source, [])}
            engagement = EngagementBlock(
                kind=stats[1],
                label=profile.engagement.label,
                covered=stats[2],
                total=int(stats[3]),
                max=int(stats[4]),
                mean=round(float(stats[5]), 2),
                buckets=[
                    NamedCount(name=b, doc_count=ordered.get(b, 0))
                    for b in _ENGAGEMENT_BUCKET_ORDER
                    if ordered.get(b, 0) > 0
                ],
            )
        blocks.append(
            SourceBlock(
                source=source,
                label=profile.label,
                doc_count=doc_count,
                captured_from=str(first) if first is not None else None,
                captured_to=str(last) if last is not None else None,
                doc_types=types_map.get(source, []),
                volume=volume_map.get(source, []),
                lanes=lanes_map.get(source, []),
                languages=langs_map.get(source, []),
                sentiment_prior_breakdown=sentiment_map.get(source, []),
                ratings=ratings_map.get(source, []),
                rating_coverage=cov_map.get(source, 0),
                rating_scale=profile.rating.scale if profile.rating else None,
                engagement=engagement,
            )
        )

    return BySourceResponse(meta=_meta(reader, project_id, batch_id), sources=blocks)
