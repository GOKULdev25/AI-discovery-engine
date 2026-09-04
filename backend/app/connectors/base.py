"""The connector protocol (A§10.1, IP§1.1). One file per source, registered
in one line (`connectors/registry.py`) — this is what makes "add a fifth
source" a small job instead of a redesign (P§5, EV-P1-10).

🔒 Connectors never call `httpx` directly. All I/O goes through `Ctx`:
`ctx.fetch()` (rate-limited, jittered, retrying), `ctx.emit()`,
`ctx.checkpoint()`, `ctx.log()`, `ctx.signal`. Politeness becomes
structural rather than something each connector author has to remember
(EV-INV-08).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import aiosqlite
import httpx
import tenacity

from app.jobs.failures import ExtractionError, FailureCode
from app.jobs.limits import LimiterRegistry
from app.projects.config import ProjectConfig

logger = logging.getLogger("app.connectors")


@dataclass
class JobSpec:
    """One unit of connector work. `params` carries whatever a connector
    needs to resolve it (country code, language, page cursor, ...)."""

    url: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"url": self.url, "params": self.params}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "JobSpec":
        return cls(url=data["url"], params=data.get("params", {}))


@dataclass
class Doc:
    """A connector's output, in A§8 shape minus the fields Ctx fills in
    (`project_id`, `batch_id`) on emit. `lane` and `extractor_version` are
    required — provenance is never optional (A§8)."""

    doc_id: str
    source: str
    doc_type: str
    source_url: str
    captured_at: str
    lane: str
    extractor_version: str
    raw: Any
    subject: str | None = None
    product_id: str | None = None
    variant: str | None = None
    authored_at: str | None = None
    author_hash: str | None = None
    text: str | None = None
    lang: str | None = None
    rating: float | None = None
    verified_purchase: bool | None = None
    engagement: dict | None = None
    parent_id: str | None = None

    def to_row(self, project_id: str, batch_id: str) -> dict[str, Any]:
        row = {
            "project_id": project_id,
            "batch_id": batch_id,
            "doc_id": self.doc_id,
            "source": self.source,
            "doc_type": self.doc_type,
            "source_url": self.source_url,
            "subject": self.subject,
            "product_id": self.product_id,
            "variant": self.variant,
            "captured_at": self.captured_at,
            "authored_at": self.authored_at,
            "author_hash": self.author_hash,
            "text": self.text,
            "lang": self.lang,
            "rating": self.rating,
            "verified_purchase": self.verified_purchase,
            "engagement": self.engagement,
            "parent_id": self.parent_id,
            "lane": self.lane,
            "extractor_version": self.extractor_version,
            "raw": self.raw,
        }
        return row


def _retryable_httpx_exc(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


class Ctx:
    """Everything a connector needs, so it never touches httpx, the
    filesystem, or the database directly (A§10.1). One Ctx per job."""

    def __init__(
        self,
        *,
        project_id: str,
        batch_id: str,
        job_id: str,
        link_id: str,
        source: str,
        ops_conn: aiosqlite.Connection,
        project_config: ProjectConfig,
        limiter_registry: LimiterRegistry,
        http_client: httpx.AsyncClient,
        on_event: Any = None,
        settings: Any = None,
    ):
        self.project_id = project_id
        self.batch_id = batch_id
        self.job_id = job_id
        self.link_id = link_id
        self.source = source
        self.config = project_config
        self.settings = settings  # app.config.Settings — provider keys, global config
        self.signal = asyncio.Event()  # set to request cooperative cancellation
        self._ops_conn = ops_conn
        self._limiter = limiter_registry.for_source(source)
        self._http = http_client
        self._on_event = on_event
        self._doc_count = 0

    @property
    def http_client(self) -> httpx.AsyncClient:
        """The shared client, for a connector that needs to reach a
        service outside `ctx.fetch()`'s per-source rate limit — Lane 3's
        AI provider calls are paced by `ai/quota.py`'s own ledger, not by
        the target *page's* politeness budget (A§4)."""
        return self._http

    async def fetch(self, url: str, **kwargs: Any) -> httpx.Response:
        """The only sanctioned way a connector performs I/O — rate-limited
        against this source's shared bucket, jittered, and retried on
        transient failures via `tenacity`."""

        async def _do() -> httpx.Response:
            async with self._limiter:
                resp = await self._http.get(url, **kwargs)
            resp.raise_for_status()
            return resp

        try:
            retrying = tenacity.AsyncRetrying(
                stop=tenacity.stop_after_attempt(4),
                wait=tenacity.wait_exponential_jitter(initial=0.5, max=8),
                retry=tenacity.retry_if_exception(_retryable_httpx_exc),
                reraise=True,
            )
            return await retrying(_do)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise ExtractionError(FailureCode.NOT_FOUND, str(exc)) from exc
            if status in (401, 403):
                raise ExtractionError(FailureCode.AUTH_REQUIRED, str(exc)) from exc
            if status == 429:
                raise ExtractionError(FailureCode.RATE_LIMITED, str(exc)) from exc
            raise ExtractionError(FailureCode.NETWORK_ERROR, str(exc)) from exc
        except httpx.TransportError as exc:
            raise ExtractionError(FailureCode.NETWORK_ERROR, str(exc)) from exc

    async def emit(self, doc: Doc) -> None:
        from app.pipeline.normalize import normalize_row

        row = normalize_row(doc.to_row(self.project_id, self.batch_id))
        now = datetime.now(timezone.utc).isoformat()
        await self._ops_conn.execute(
            """INSERT INTO staging_docs (doc_id, project_id, batch_id, row_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (doc.doc_id, self.project_id, self.batch_id, json.dumps(row), now),
        )
        await self._ops_conn.commit()
        self._doc_count += 1
        if self._on_event:
            await self._on_event("link.docs", {"link_id": self.link_id, "doc_count": self._doc_count})

    async def checkpoint(self, cursor: str | None) -> None:
        from app.jobs.checkpoint import save_checkpoint

        await save_checkpoint(self._ops_conn, self.job_id, self.link_id, cursor)

    async def call_paced(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """For a connector that must use a synchronous third-party client
        instead of `ctx.fetch()` (Play Store's `google-play-scraper` does
        its own undocumented batchexecute RPC — reimplementing it is out
        of scope). Applies this source's rate limit/jitter exactly like
        `ctx.fetch()` does, then runs the blocking call in a thread so it
        never stalls the event loop. This is the one sanctioned exception
        to "connectors never do I/O outside ctx" (EV-INV-08 only greps
        for direct `httpx` usage, which this deliberately isn't)."""
        async with self._limiter:
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def call_paced_async(self, coro_fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Like `call_paced`, for a connector using an async third-party
        client that does its own networking (`asyncpraw`) instead of
        `ctx.fetch()`. The client's own internal rate limiting is scoped
        to itself; this is what makes the limit global across projects
        (A§10.2, EV-P1-09) regardless of that."""
        async with self._limiter:
            return await coro_fn(*args, **kwargs)

    def log(self, message: str, **fields: Any) -> None:
        logger.info(
            json.dumps({
                "message": message,
                "project_id": self.project_id,
                "batch_id": self.batch_id,
                "link_id": self.link_id,
                "source": self.source,
                **fields,
            })
        )


class Connector(Protocol):
    id: str
    lane: str

    def match(self, url: str) -> JobSpec | None: ...

    async def expand(self, job: JobSpec, ctx: Ctx) -> list[JobSpec]: ...

    def run(self, job: JobSpec, ctx: Ctx) -> AsyncIterator[Doc]: ...
