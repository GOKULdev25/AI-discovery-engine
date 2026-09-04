"""EV-P1-10 — "add a fifth source is one file": a new connector needs one
line in `registry.py` and zero edits to any core module (P§5, A§10.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.connectors import registry as connector_registry
from app.connectors.base import Ctx, Doc, JobSpec
from evals.registry import eval_case


class _ProbeConnector:
    """A throwaway fifth connector. Registering it is the whole test —
    nothing about `Ctx`, the job engine, or the API needs to know it
    exists ahead of time."""

    id = "probe"
    lane = "api"

    def match(self, url: str) -> JobSpec | None:
        if not url.startswith("probe://"):
            return None
        return JobSpec(url=url)

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]:
        return [job]

    async def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]:
        yield Doc(
            doc_id="probe-doc-1", source="probe", doc_type="review",
            source_url=job.url, captured_at="2026-08-29T00:00:00Z",
            lane="api", extractor_version="probe-1", raw={},
        )


@eval_case(
    "EV-P1-10",
    proves='"Add a fifth source" is one file: a new connector registers with one line, zero edits to core modules',
    source="P§5",
    severity="MAJOR",
    tags=["phase:P1"],
)
async def ev_p1_10():
    probe = _ProbeConnector()
    connector_registry._CONNECTORS.append(probe)  # the "one line" — everything else below just uses it
    try:
        match = connector_registry.classify("probe://some-thread")
        assert match is not None, "registry.classify() didn't pick up the newly registered connector"
        connector, job = match
        assert connector is probe
        assert connector_registry.get_by_id("probe") is probe

        docs = [doc async for doc in connector.run(job, ctx=None)]  # this connector never touches ctx
        assert len(docs) == 1
        assert docs[0].source == "probe"
    finally:
        connector_registry._CONNECTORS.remove(probe)
