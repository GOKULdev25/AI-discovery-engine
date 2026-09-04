"""Per-project relevance gate configuration (A§7.2, A§11.2).

The embedding gate scores every document against this project's own
prototype sentences. Those sentences have always been per-project and
editable on disk (`<project>/gate/prototypes.yaml`), but nothing exposed
them — so a project whose starter prototypes describe app crashes while
its corpus is video comments silently banded ~all of it `drop`, and since
chat retrieval skips dropped documents, the chatbot quietly had nothing
to read.

Editing prototypes re-bands documents, so `PUT` clears the stored bands
for this project and lets the normal enrichment pass recompute them —
never a partial rewrite that would leave two eras of banding mixed
together in one chart.
"""

from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import settings_dep
from app.config import Settings
from app.pipeline import gate
from app.pipeline.enrich import regate_documents
from app.projects.resolver import get_resolver
from app.store import duckdb as dk

router = APIRouter(prefix="/projects/{project_id}/gate", tags=["gate"])

# A guard against a paste of the entire corpus into the prototype list:
# every prototype is embedded and compared against every document, so the
# cost of stage 2 is linear in this number.
_MAX_PROTOTYPES = 25
_MAX_PROTOTYPE_CHARS = 500


class GateBandCount(BaseModel):
    band: str
    doc_count: int


class PrototypesResponse(BaseModel):
    keep: list[str]
    drop: list[str]
    bands: list[GateBandCount]
    document_count: int
    # True when the gate is discarding so much that everything downstream
    # of it — chat retrieval above all — is effectively starved.
    starved: bool


class PrototypesRequest(BaseModel):
    keep: list[str] = Field(default_factory=list)
    drop: list[str] = Field(default_factory=list)


def _read_bands(reader) -> tuple[list[GateBandCount], int]:
    rows = reader.execute(
        """SELECT COALESCE(e.gate_band, 'ungated') AS band, COUNT(*) AS doc_count
           FROM documents d LEFT JOIN enrichment e ON d.doc_id = e.doc_id
           GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    bands = [GateBandCount(band=r[0], doc_count=r[1]) for r in rows]
    total = sum(b.doc_count for b in bands)
    return bands, total


def _starved(bands: list[GateBandCount], total: int) -> bool:
    if total == 0:
        return False
    usable = sum(b.doc_count for b in bands if b.band != "drop")
    return usable / total < 0.05


@router.get("/prototypes", response_model=PrototypesResponse)
async def get_prototypes(project_id: str, settings: Settings = Depends(settings_dep)):
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)
    loaded = gate.load_prototypes(project_dir / "gate" / "prototypes.yaml")
    reader = await dk.get_reader(project_dir)
    bands, total = _read_bands(reader)
    return PrototypesResponse(
        keep=loaded["keep"],
        drop=loaded["drop"],
        bands=bands,
        document_count=total,
        starved=_starved(bands, total),
    )


@router.put("/prototypes", response_model=PrototypesResponse)
async def put_prototypes(
    project_id: str,
    body: PrototypesRequest,
    settings: Settings = Depends(settings_dep),
):
    """Replaces this project's prototypes and re-gates its documents.

    Both lists must be non-empty: stage 2 scores `best_keep - best_drop`,
    so a missing side makes every score one-sided and pushes the whole
    corpus to one band.
    """
    resolver = get_resolver(settings)
    project_dir = resolver.require_exists(project_id)

    keep = [s.strip() for s in body.keep if s and s.strip()]
    drop = [s.strip() for s in body.drop if s and s.strip()]
    if not keep or not drop:
        raise HTTPException(
            422, "both keep and drop need at least one example sentence"
        )
    if len(keep) > _MAX_PROTOTYPES or len(drop) > _MAX_PROTOTYPES:
        raise HTTPException(422, f"at most {_MAX_PROTOTYPES} prototypes per side")
    if any(len(s) > _MAX_PROTOTYPE_CHARS for s in keep + drop):
        raise HTTPException(
            422, f"each prototype must be under {_MAX_PROTOTYPE_CHARS} characters"
        )

    path = project_dir / "gate" / "prototypes.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# gate/prototypes.yaml — edited from the app's Relevance settings.\n"
        "# Write concrete example sentences a real document might contain,\n"
        "# not abstract descriptions of a category (A§11.2, FEASIBILITY_LOG).\n\n"
    )
    path.write_text(
        header + yaml.safe_dump({"keep": keep, "drop": drop}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Re-gate immediately against the new prototypes, reusing the stored
    # embeddings. Only the gate columns move: a prototype change affects
    # the keep-vs-drop comparison and nothing else, so language, sentiment
    # prior, simhash and the vectors all stay valid. Free and offline —
    # no model call, no network.
    committer = await dk.get_committer(project_dir)
    await regate_documents(project_dir, committer)

    reader = await dk.get_reader(project_dir)
    bands, total = _read_bands(reader)
    return PrototypesResponse(
        keep=keep,
        drop=drop,
        bands=bands,
        document_count=total,
        starved=_starved(bands, total),
    )
