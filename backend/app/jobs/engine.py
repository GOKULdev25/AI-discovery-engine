"""The asyncio worker pool (A§10.2, IP§0.4). No Celery, no Redis, no
Postgres (A§6) — one `ProjectEngine` per active project, workers claiming
through `jobs/claim.py`'s atomic UPDATE, never an `asyncio.Queue`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

import aiosqlite
import httpx

from app.ai.providers.factory import build_providers
from app.browser import session as browser_session
from app.chat.index_fts import sync_fts_index
from app.config import Settings
from app.connectors import registry as connector_registry
from app.connectors.base import Ctx, JobSpec
from app.http_client import new_http_client
from app.jobs import checkpoint as ckpt
from app.jobs import claim
from app.jobs.events import get_event_bus
from app.jobs.failures import ExtractionError, FailureCode
from app.jobs.limits import get_limiter_registry
from app.pipeline import commit as pipeline_commit
from app.pipeline.classify import classify_pending_documents
from app.pipeline.enrich import enrich_pending_documents
from app.projects import scaffold
from app.projects.resolver import get_resolver
from app.store import duckdb as dk
from app.store import sqlite as sq

logger = logging.getLogger("app.jobs.engine")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchTooLarge(ValueError):
    def __init__(self, count: int, limit: int):
        self.count = count
        self.limit = limit
        super().__init__(f"{count} links exceeds the {limit}-link batch limit")


def classify_url(url: str) -> tuple[str | None, object | None]:
    """Returns (failure_code, None) if invalid/unsupported, or
    (None, JobSpec-bearing-connector-tuple) if a connector matches.
    A URL that fails to classify never blocks the rest of the batch
    (IP decision 5, P§6 'fail loudly')."""
    url = (url or "").strip()
    if not url:
        return FailureCode.INVALID_URL.value, None
    if url.startswith("fixture://"):
        pass
    elif not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url):
        return FailureCode.INVALID_URL.value, None

    match = connector_registry.classify(url)
    if match is None:
        return FailureCode.UNSUPPORTED_SOURCE.value, None
    return None, match


class ProjectEngine:
    def __init__(self, settings: Settings, project_id: str):
        self.settings = settings
        self.project_id = project_id
        self.resolver = get_resolver(settings)
        self.project_dir = self.resolver.project_dir(project_id)
        self.limiter_registry = get_limiter_registry()
        self.event_bus = get_event_bus()
        self._http_client = new_http_client(timeout=httpx.Timeout(30.0), follow_redirects=True)
        self._worker_tasks: list[asyncio.Task] = []
        self._reaper_task: asyncio.Task | None = None
        self._drain_task: asyncio.Task | None = None
        self._classify_task: asyncio.Task | None = None
        self._drain_lock = asyncio.Lock()
        self._started = False
        self._committer: dk.Committer | None = None

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._committer = await dk.get_committer(self.project_dir)
        for i in range(self.settings.worker_count):
            self._worker_tasks.append(
                asyncio.create_task(self._worker_loop(f"{self.project_id}-w{i}"))
            )
        self._reaper_task = asyncio.create_task(self._reaper_loop())
        self._drain_task = asyncio.create_task(self._drain_loop())
        if self.settings.ai_classification_enabled:
            self._classify_task = asyncio.create_task(self._classify_loop())

    async def stop(self) -> None:
        self._started = False
        tasks = [*self._worker_tasks]
        if self._reaper_task:
            tasks.append(self._reaper_task)
        if self._drain_task:
            tasks.append(self._drain_task)
        if self._classify_task:
            tasks.append(self._classify_task)
        for t in tasks:
            t.cancel()
        # Await cancellation rather than firing and forgetting: each loop's
        # `finally` closes its own ops.sqlite connection, and a caller that
        # deletes this project's directory right after `stop()` returns
        # (projects/scaffold.py) needs that handle actually released first,
        # especially on Windows where an open file blocks its own removal.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._worker_tasks = []
        self._reaper_task = None
        self._drain_task = None
        self._classify_task = None
        await self._http_client.aclose()

    async def _drain_loop(self) -> None:
        async with sq.ops_db(self.project_dir) as ops_conn:
            while True:
                await asyncio.sleep(self.settings.drain_interval_seconds)
                try:
                    await self._drain_staging(ops_conn)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("periodic drain failed for project %s", self.project_id)

    async def _reaper_loop(self) -> None:
        async with sq.ops_db(self.project_dir) as ops_conn:
            while True:
                await asyncio.sleep(max(5, self.settings.stale_claim_seconds // 4))
                try:
                    reaped = await claim.reap_stale_claims(ops_conn, self.settings.stale_claim_seconds)
                    if reaped:
                        logger.info("reaped %d stale job(s) for project %s", reaped, self.project_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("stale-claim reaper failed for project %s", self.project_id)

    async def _classify_loop(self) -> None:
        """Gate stage 3 (A§11.2, IP§3.2) — polls for whatever the local
        gate left "ambiguous" and resolves it through the AI router.
        Its own `app.sqlite` connection, same reasoning as every other
        loop here: never a shared singleton across concurrent coroutines."""
        async with sq.app_db(self.settings.app_sqlite_path) as app_conn:
            while True:
                await asyncio.sleep(self.settings.classify_interval_seconds)
                try:
                    assert self._committer is not None
                    providers = build_providers(self.settings, self._http_client)
                    prototypes_path = self.resolver.gate_prototypes_path(self.project_id)
                    resolved = await classify_pending_documents(
                        self._committer, app_conn, providers, prototypes_path,
                        batch_size=self.settings.classify_batch_size,
                    )
                    if resolved:
                        logger.info("classified %d document(s) for project %s", resolved, self.project_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("classify loop failed for project %s", self.project_id)

    async def _worker_loop(self, worker_id: str) -> None:
        # Its own connection — never shared with other workers. Sharing one
        # aiosqlite connection across concurrent coroutines can raise
        # "cannot commit transaction - SQL statements in progress" when one
        # caller's SELECT hasn't been fully fetched while another commits
        # (see `store/sqlite.ops_db`).
        async with sq.ops_db(self.project_dir) as ops_conn:
            while True:
                try:
                    job = await claim.claim_next_job(ops_conn, worker_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("claim failed for worker %s", worker_id)
                    await asyncio.sleep(1)
                    continue
                if job is None:
                    await asyncio.sleep(0.2)
                    continue
                await self._process_job(ops_conn, job)

    async def _process_job(self, ops_conn: aiosqlite.Connection, job: dict) -> None:
        link_id = job["link_id"]
        batch_id = job["batch_id"]
        connector = connector_registry.get_by_id(job["connector_id"])
        job_spec = JobSpec.from_json(job["job_spec"])

        cursor = await ckpt.load_checkpoint(ops_conn, job["id"])
        if cursor:
            job_spec.params["_resume_after"] = cursor

        project_config = scaffold.load_project_config(self.resolver, self.project_id)

        async def on_event(event_type: str, payload: dict) -> None:
            await self.event_bus.publish(ops_conn, batch_id, event_type, payload)

        ctx = Ctx(
            project_id=self.project_id,
            batch_id=batch_id,
            job_id=job["id"],
            link_id=link_id,
            source=job["source"],
            ops_conn=ops_conn,
            project_config=project_config,
            limiter_registry=self.limiter_registry,
            http_client=self._http_client,
            on_event=on_event,
            settings=self.settings,
        )

        await self._set_link_status(ops_conn, link_id, "running")
        await on_event("link.status", {"link_id": link_id, "status": "running"})

        # Draining to the warehouse happens on `_drain_loop` (periodic) and
        # once more, guaranteed, right before a batch is marked done
        # (`_emit_batch_progress`) — not here, per job. A DuckDB commit has
        # a large fixed cost on this platform regardless of row count
        # (~350-700ms observed), so draining once per completed job turned
        # a sub-second batch into a multi-second one for no benefit: SSE
        # progress already comes from `staging_docs` + the event bus, not
        # from the warehouse.
        doc_count = 0
        try:
            async for doc in connector.run(job_spec, ctx):
                await ctx.emit(doc)
                doc_count += 1
            await claim.mark_done(ops_conn, job["id"])
            await self._on_job_terminal(ops_conn, job, on_event, success=True, doc_count=doc_count)
        except ExtractionError as exc:
            await claim.mark_failed(
                ops_conn, job["id"], exc.code.value, exc.retryable, job["attempts"],
                max_attempts=self.settings.max_retryable_attempts,
                backoff_base_seconds=self.settings.retry_backoff_base_seconds,
                backoff_max_seconds=self.settings.retry_backoff_max_seconds,
            )
            await on_event(
                "job.error",
                {"link_id": link_id, "code": exc.code.value, "retryable": exc.retryable, "message": str(exc)},
            )
            await self._on_job_terminal(
                ops_conn, job, on_event, success=False, doc_count=doc_count,
                failure_code=exc.code.value, retryable=exc.retryable,
            )
        except Exception as exc:  # boundary: converts an unexpected bug into
            # the one taxonomy code reserved for exactly this (A§8.1
            # EXTRACTOR_CRASH — "surfaced, never swallowed"). The job is
            # marked failed and a job.error event fires; nothing here
            # continues silently, which is what distinguishes this from
            # the swallowed-exception pattern EV-INV-07 forbids.
            logger.exception("extractor crashed for link %s", link_id)
            await claim.mark_failed(ops_conn, job["id"], FailureCode.EXTRACTOR_CRASH.value, False)
            await on_event(
                "job.error",
                {"link_id": link_id, "code": FailureCode.EXTRACTOR_CRASH.value, "retryable": False, "message": str(exc)},
            )
            await self._on_job_terminal(
                ops_conn, job, on_event, success=False, doc_count=doc_count,
                failure_code=FailureCode.EXTRACTOR_CRASH.value, retryable=False,
            )

    async def _drain_staging(self, ops_conn: aiosqlite.Connection) -> int:
        """Drains `staging_docs` into the warehouse via `pipeline/commit.py`
        (A§9 🔒 single-writer committer), then runs local enrichment +
        the gate over whatever was newly committed (A§11.2).

        Guarded by `_drain_lock` because both the periodic `_drain_loop`
        and the guaranteed pre-`batch.done` flush (`_emit_batch_progress`)
        call this — without the lock they could race on the same
        uncommitted rows."""
        assert self._committer is not None
        async with self._drain_lock:
            drained = await pipeline_commit.drain_staging(ops_conn, self._committer)
            if drained:
                try:
                    await enrich_pending_documents(self.project_dir, self._committer)
                except Exception:
                    # Enrichment is a value-add over already-durable data,
                    # never a reason to fail extraction — log and let the
                    # next drain cycle retry these same still-unenriched
                    # rows (enrich_pending_documents re-queries for them).
                    logger.exception("local enrichment failed for project %s", self.project_id)
                try:
                    # FTS sync rides on enrichment.enriched_at (chat/index_fts.py)
                    # so it must run after enrichment, not alongside it.
                    await sync_fts_index(ops_conn, self._committer.cursor())
                except Exception:
                    logger.exception("FTS sync failed for project %s", self.project_id)
            return drained

    async def _set_link_status(
        self, ops_conn: aiosqlite.Connection, link_id: str,
        status: str, failure_code: str | None = None, retryable: bool | None = None,
    ) -> None:
        await ops_conn.execute(
            """UPDATE links SET status = ?, failure_code = ?, retryable = ?, updated_at = ?
               WHERE id = ?""",
            (status, failure_code, None if retryable is None else int(retryable), _now(), link_id),
        )
        await ops_conn.commit()

    async def _on_job_terminal(
        self, ops_conn: aiosqlite.Connection, job: dict, on_event,
        *, success: bool, doc_count: int = 0,
        failure_code: str | None = None, retryable: bool | None = None,
    ) -> None:
        link_id = job["link_id"]
        batch_id = job["batch_id"]

        if doc_count:
            await ops_conn.execute(
                "UPDATE links SET doc_count = doc_count + ?, updated_at = ? WHERE id = ?",
                (doc_count, _now(), link_id),
            )
            await ops_conn.commit()

        cur = await ops_conn.execute(
            "SELECT status, failure_code, retryable FROM jobs WHERE link_id = ?", (link_id,)
        )
        rows = await cur.fetchall()
        total = len(rows)
        done = sum(1 for r in rows if r["status"] == "done")
        failed = sum(1 for r in rows if r["status"] == "failed")

        if done + failed >= total:
            if failed == total:
                last = rows[-1]
                await self._set_link_status(ops_conn, link_id, "failed", last["failure_code"], bool(last["retryable"]))
            else:
                await self._set_link_status(ops_conn, link_id, "done")
            cur2 = await ops_conn.execute("SELECT status, failure_code, retryable FROM links WHERE id = ?", (link_id,))
            row2 = await cur2.fetchone()
            await on_event("link.status", {
                "link_id": link_id, "status": row2["status"],
                "failure_code": row2["failure_code"], "retryable": bool(row2["retryable"]) if row2["retryable"] is not None else None,
            })

        await self._emit_batch_progress(ops_conn, batch_id, on_event)

    async def _emit_batch_progress(self, ops_conn: aiosqlite.Connection, batch_id: str, on_event) -> None:
        cur = await ops_conn.execute(
            "SELECT status, COUNT(*) c FROM links WHERE batch_id = ? GROUP BY status", (batch_id,)
        )
        rows = await cur.fetchall()
        counts = {r["status"]: r["c"] for r in rows}
        total = sum(counts.values())
        terminal = counts.get("done", 0) + counts.get("failed", 0)
        await on_event("batch.progress", {"batch_id": batch_id, "total": total, "terminal": terminal, "counts": counts})
        if total > 0 and terminal >= total:
            # Guaranteed flush: the periodic drain loop keeps the warehouse
            # eventually consistent, but `batch.done` is a promise that
            # every one of this batch's documents is actually queryable —
            # so drain once more, synchronously, before making that promise.
            await self._drain_staging(ops_conn)
            await ops_conn.execute(
                "UPDATE batches SET status = 'done', updated_at = ? WHERE id = ?", (_now(), batch_id)
            )
            await ops_conn.commit()
            await on_event("batch.done", {"batch_id": batch_id, "total": total})


_engines: dict[str, ProjectEngine] = {}
_engines_lock = asyncio.Lock()


async def get_engine(settings: Settings, project_id: str) -> ProjectEngine:
    async with _engines_lock:
        engine = _engines.get(project_id)
        if engine is None:
            engine = ProjectEngine(settings, project_id)
            await engine.start()
            _engines[project_id] = engine
        return engine


async def resume_active_projects(settings: Settings) -> int:
    """Called once at API startup (main.py lifespan). A killed backend must
    resume in-flight batches on its own restart, not wait for the next
    incoming API call — otherwise stale claims sit unreaped and pending
    jobs sit unclaimed until something unrelated happens to touch that
    project (EV-P0-05)."""
    resolver = get_resolver(settings)
    resumed = 0
    for project_id in resolver.list_project_ids():
        project_dir = resolver.project_dir(project_id)
        async with sq.ops_db(project_dir) as ops_conn:
            cur = await ops_conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE status IN ('pending', 'running')"
            )
            row = await cur.fetchone()
        if row["c"] > 0:
            await get_engine(settings, project_id)
            resumed += 1
    return resumed


async def forget_engine(project_id: str) -> None:
    """Stops and drops one project's engine — used by the eval harness to
    tear down a temp project without waiting for process exit, and
    available for the same purpose ahead of a project delete."""
    async with _engines_lock:
        engine = _engines.pop(project_id, None)
    if engine is not None:
        await engine.stop()
        # A project that ever touched the browser lane holds a real Chrome
        # process + persistent profile — leaving it open would leak a
        # process per eval/project and lock the profile directory against
        # deletion (Windows holds file locks on a running Chrome's cache).
        await browser_session.close_context(engine.project_dir)


async def stop_all_engines() -> None:
    async with _engines_lock:
        engines = list(_engines.values())
        _engines.clear()
    for e in engines:
        await e.stop()


async def submit_batch(settings: Settings, project_id: str, urls: list[str]) -> tuple[str, list[dict]]:
    """Classifies each URL and writes rows as pending, then returns
    immediately (A§13) — actual extraction runs in the background via the
    project's already-running (or just-started) worker pool. One bad link
    never costs the batch (decision 5, EV-P0-10)."""
    if len(urls) > settings.max_batch_links:
        raise BatchTooLarge(len(urls), settings.max_batch_links)

    resolver = get_resolver(settings)
    project_dir = resolver.project_dir(project_id)

    batch_id = uuid.uuid4().hex
    now = _now()
    link_summaries = []
    project_config = scaffold.load_project_config(resolver, project_id)

    async with sq.ops_db(project_dir) as ops_conn:
        await ops_conn.execute(
            "INSERT INTO batches (id, project_id, status, created_at, updated_at, link_count) VALUES (?, ?, 'running', ?, ?, ?)",
            (batch_id, project_id, now, now, len(urls)),
        )

        # One client for the whole batch's expand() calls — constructing an
        # httpx.AsyncClient is not free (connection pool + proxy/env probing),
        # and expand() itself does no real I/O for any Phase 1 connector, so
        # creating one per link turns a sub-millisecond loop into a
        # multi-second one for nothing.
        async with new_http_client() as expand_http:
            for url in urls:
                link_id = uuid.uuid4().hex
                failure_code, match = classify_url(url)
                if failure_code is not None:
                    await ops_conn.execute(
                        """INSERT INTO links (id, batch_id, project_id, url, connector_id, status,
                           failure_code, retryable, created_at, updated_at)
                           VALUES (?, ?, ?, ?, NULL, 'failed', ?, 0, ?, ?)""",
                        (link_id, batch_id, project_id, url, failure_code, now, now),
                    )
                    link_summaries.append({"link_id": link_id, "url": url, "status": "failed", "failure_code": failure_code})
                    continue

                connector, job_spec = match
                if connector.lane != "api":
                    # A Lane 1 -> Lane 2 downgrade is always a visible
                    # event, never a silent log line (A§4): the run still
                    # succeeds, but at browser-lane cost and ceilings, and
                    # nobody should have to notice that for weeks by
                    # accident.
                    await get_event_bus().publish(ops_conn, batch_id, "lane.downgrade", {
                        "link_id": link_id, "url": url, "from_lane": "api", "to_lane": connector.lane,
                        "reason": f"no Lane 1 connector for this source — routed to {connector.id}",
                    })
                await ops_conn.execute(
                    """INSERT INTO links (id, batch_id, project_id, url, connector_id, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (link_id, batch_id, project_id, url, connector.id, now, now),
                )

                expand_ctx = Ctx(
                    project_id=project_id, batch_id=batch_id, job_id=f"expand:{link_id}", link_id=link_id,
                    source=connector.id, ops_conn=ops_conn, project_config=project_config,
                    limiter_registry=get_limiter_registry(), http_client=expand_http,
                    settings=settings,
                )
                job_specs = await connector.expand(job_spec, expand_ctx)

                for spec in job_specs:
                    job_id = uuid.uuid4().hex
                    await claim.enqueue_job(
                        ops_conn, job_id=job_id, project_id=project_id, batch_id=batch_id,
                        link_id=link_id, connector_id=connector.id, source=connector.id,
                        job_spec=spec.to_json(),
                    )
                link_summaries.append({"link_id": link_id, "url": url, "status": "pending", "job_count": len(job_specs)})

        await ops_conn.commit()

    await get_engine(settings, project_id)  # ensure workers are running
    return batch_id, link_summaries


async def retry_batch(settings: Settings, project_id: str, batch_id: str) -> int:
    """Re-runs only the retryable failures (A§8.1, EV-P0-09).

    Re-classifies and re-expands each link exactly like `submit_batch`
    does, rather than trusting the stored `connector_id` with a bare
    `JobSpec(url=...)` — two real bugs found live (2026-08-29) fetching a
    real YouTube link: (1) `match()` is what populates `params`
    (video_id, app_id, country, ...) from the URL, so a connector that
    reads `job.params` instead of re-parsing its own URL — App Store,
    Play Store, YouTube all do — crashed with a KeyError on retry (only
    the fixture connector happened to survive, since it re-parses params
    from the URL itself); (2) skipping `expand()` meant a multi-locale
    link (e.g. App Store's 3-country fan-out) would retry as a single
    job instead of recreating the full fan-out.
    """
    resolver = get_resolver(settings)
    project_dir = resolver.project_dir(project_id)
    project_config = scaffold.load_project_config(resolver, project_id)

    async with sq.ops_db(project_dir) as ops_conn:
        cur = await ops_conn.execute(
            "SELECT id, url, connector_id FROM links WHERE batch_id = ? AND status = 'failed' AND retryable = 1",
            (batch_id,),
        )
        rows = await cur.fetchall()
        retried_count = 0

        async with new_http_client() as expand_http:
            for row in rows:
                failure_code, match = classify_url(row["url"])
                if failure_code is not None or match is None:
                    continue  # the URL stopped being classifiable; leave it failed
                connector, job_spec = match
                retried_count += 1

                expand_ctx = Ctx(
                    project_id=project_id, batch_id=batch_id, job_id=f"retry-expand:{row['id']}",
                    link_id=row["id"], source=connector.id, ops_conn=ops_conn,
                    project_config=project_config, limiter_registry=get_limiter_registry(),
                    http_client=expand_http,
                )
                job_specs = await connector.expand(job_spec, expand_ctx)

                for spec in job_specs:
                    job_id = uuid.uuid4().hex
                    await claim.enqueue_job(
                        ops_conn, job_id=job_id, project_id=project_id, batch_id=batch_id,
                        link_id=row["id"], connector_id=connector.id, source=connector.id,
                        job_spec=spec.to_json(),
                    )
                await ops_conn.execute(
                    "UPDATE links SET status = 'pending', failure_code = NULL, retryable = NULL, updated_at = ? WHERE id = ?",
                    (_now(), row["id"]),
                )
            if retried_count:
                # Without this, `batches.status` stays stuck at 'done' from
                # before the retry while a link is genuinely back in
                # flight — found live, 2026-08-29: GET /batches/{id}
                # reported "done" with a link simultaneously "running".
                await ops_conn.execute(
                    "UPDATE batches SET status = 'running', updated_at = ? WHERE id = ?",
                    (_now(), batch_id),
                )
        await ops_conn.commit()

    await get_engine(settings, project_id)
    return retried_count
