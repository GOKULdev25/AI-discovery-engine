"""Serves the source capability profiles (`app/sources/profiles.py`) so the
frontend can render a panel per source from data rather than hardcoding a
branch per source.

Deliberately project-independent and unauthenticated-by-shape: these are
static facts about connectors, not about anyone's collected data, so there
is nothing here to scope to a project and nothing to leak between them.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.sources.profiles import COMPARABLE_DIMENSIONS, all_profiles

router = APIRouter(prefix="/sources", tags=["sources"])


class EngagementSpecOut(BaseModel):
    key: str
    label: str
    extras: list[list[str]]


class RatingSpecOut(BaseModel):
    scale: float
    label: str


class SourceProfileOut(BaseModel):
    id: str
    label: str
    doc_types: list[str]
    rating: RatingSpecOut | None
    engagement: EngagementSpecOut | None
    threaded: bool
    verified_purchase: bool
    subject_label: str | None
    product_id_label: str | None
    variant_label: str | None
    notes: str | None


class ProfilesResponse(BaseModel):
    profiles: list[SourceProfileOut]
    # Which dimensions the "all sources" view may legitimately combine.
    # Ratings and engagement are absent on purpose — see the constant's
    # own comment for why (A§12).
    comparable_dimensions: list[str]


@router.get("/profiles", response_model=ProfilesResponse)
async def get_source_profiles() -> ProfilesResponse:
    """What each source provides. Drives which charts and which document
    fields the UI renders, so a rating axis never appears for a source
    that has no ratings."""
    out = []
    for p in all_profiles():
        out.append(
            SourceProfileOut(
                id=p.id,
                label=p.label,
                doc_types=list(p.doc_types),
                rating=(
                    RatingSpecOut(scale=p.rating.scale, label=p.rating.label)
                    if p.rating is not None
                    else None
                ),
                engagement=(
                    EngagementSpecOut(
                        key=p.engagement.key,
                        label=p.engagement.label,
                        extras=[[k, lbl] for k, lbl in p.engagement.extras],
                    )
                    if p.engagement is not None
                    else None
                ),
                threaded=p.threaded,
                verified_purchase=p.verified_purchase,
                subject_label=p.subject_label,
                product_id_label=p.product_id_label,
                variant_label=p.variant_label,
                notes=p.notes,
            )
        )
    return ProfilesResponse(
        profiles=out, comparable_dimensions=list(COMPARABLE_DIMENSIONS)
    )
