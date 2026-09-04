"""Orchestrates one chat turn (A§12, IP§5): retrieve evidence, ask the
grounding contract to route + validate, persist both sides of the turn to
`ops.sqlite` (EV-P5-11 — a study's thread survives a restart), and return
a `GroundedAnswer` the API layer serializes.

A turn that can't be answered safely — every provider exhausted, or the
model's own response fails `grounding.validate_response` — degrades to
an honest decline. It never surfaces an unvalidated answer (EVAL.md
§10.3: citation integrity is never quarantined, never softened).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
import duckdb

from app.ai import router
from app.ai.providers.base import Provider, ProviderQuotaExhausted
from app.chat import grounding
from app.chat.retrieval import hybrid_retrieve

logger = logging.getLogger("app.chat.service")

_DECLINE = grounding.GroundedAnswer(
    type="insufficient_evidence",
    text="I couldn't produce a reliably grounded answer for that question right now — please try rephrasing it, or try again shortly.",
    citations=[],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _persist_message(
    ops_conn: aiosqlite.Connection, project_id: str, batch_id: str | None, role: str, content: str, citations: list[str] | None
) -> None:
    import json

    await ops_conn.execute(
        "INSERT INTO chat_messages (id, project_id, batch_id, role, content, citations, created_at) VALUES (?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, project_id, batch_id, role, content, json.dumps(citations) if citations else None, _now()),
    )
    await ops_conn.commit()


async def ask(
    ops_conn: aiosqlite.Connection,
    app_conn: aiosqlite.Connection,
    reader: duckdb.DuckDBPyConnection,
    providers: list[Provider],
    project_id: str,
    question: str,
    *,
    batch_id: str | None = None,
    source: str | None = None,
    top_k: int = 10,
) -> dict:
    await _persist_message(ops_conn, project_id, batch_id, "user", question, None)

    evidence = await hybrid_retrieve(
        ops_conn, reader, question, batch_id=batch_id, source=source, top_k=top_k
    )
    caveats = grounding.compute_caveats(evidence) if evidence else {"cross_source": False, "cross_time": False}

    if not evidence:
        answer = grounding.GroundedAnswer(
            type="insufficient_evidence",
            text="I don't have any collected documents to answer that from yet.",
            citations=[],
        )
    else:
        prompt = grounding.build_prompt(question, evidence, caveats)
        try:
            result = await router.route(app_conn, providers, prompt)
            answer = grounding.validate_response(result.data, evidence)
        except ProviderQuotaExhausted:
            logger.info("chat: every provider exhausted for project %s", project_id)
            answer = _DECLINE
        except grounding.GroundingViolation:
            logger.exception("chat: response failed grounding validation for project %s", project_id)
            answer = _DECLINE

    await _persist_message(ops_conn, project_id, batch_id, "assistant", answer.text, answer.citations)

    return {
        "type": answer.type,
        "text": answer.text,
        "citations": answer.citations,
        "caveats": caveats,
        "evidence_count": len(evidence),
    }
