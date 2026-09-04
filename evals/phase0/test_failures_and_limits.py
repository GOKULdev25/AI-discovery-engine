"""EV-P0-09, 10, 11 — typed failures, retry scoping, and the batch-size
bound (decision 5, C§12.8)."""

from __future__ import annotations

from evals.harness import api_client, temp_project, wait_for_batch_done
from evals.registry import eval_case


@eval_case(
    "EV-P0-09",
    proves="A failing link surfaces a typed code with its retryable flag; retry re-runs only retryable ones",
    source="A§8.1",
    severity="BLOCKER",
    tags=["phase:P0"],
)
async def ev_p0_09():
    # max_retryable_attempts=1 makes a retryable failure terminal on its
    # first attempt, so this eval doesn't have to sit through a real
    # backoff cycle to reach a stable, assertable state.
    async with temp_project("p0-09", max_retryable_attempts=1) as (settings, resolver, project_id):
        async with api_client(settings) as client:
            urls = [
                "fixture://run?count=5&latency_ms=0&fail_at=2&fail_code=RATE_LIMITED",   # retryable
                "fixture://run?count=5&latency_ms=0&fail_at=2&fail_code=PARSE_ERROR",    # not retryable
            ]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            batch_id = resp.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch_id)

            links = (await client.get(f"/projects/{project_id}/batches/{batch_id}/links")).json()
            by_url = {l["url"]: l for l in links}
            rate_limited = by_url[urls[0]]
            parse_error = by_url[urls[1]]
            assert rate_limited["failure_code"] == "RATE_LIMITED"
            assert rate_limited["retryable"] == 1
            assert parse_error["failure_code"] == "PARSE_ERROR"
            assert parse_error["retryable"] == 0

            retry_resp = await client.post(f"/projects/{project_id}/batches/{batch_id}/retry")
            assert retry_resp.json()["retried"] == 1, "retry should only re-queue the retryable link"

            # 30s, not 5s: the retried link goes through a real backoff and a
            # real DuckDB commit, and under machine load 5s left no margin at
            # all — the same flake class as EV-P0-03/05/10, and fixed the same
            # way. `wait_for_batch_done` raises `TimeoutError`, which the runner
            # reports as a per-eval hang, so a tight internal wait shows up as
            # BLOCKED rather than as the load problem it actually is.
            await wait_for_batch_done(client, project_id, batch_id, timeout=30)
            links_after = (await client.get(f"/projects/{project_id}/batches/{batch_id}/links")).json()
            by_url_after = {l["url"]: l for l in links_after}
            # The non-retryable link must be completely untouched by retry.
            assert by_url_after[urls[1]]["failure_code"] == "PARSE_ERROR"


@eval_case(
    "EV-P0-10",
    proves="One bad link never costs the rest of the batch: 200 links, 2 bad -> 198 proceed, 2 typed",
    source="P§6",
    severity="BLOCKER",
    tags=["phase:P0", "slow"],
)
async def ev_p0_10():
    async with temp_project("p0-10") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            urls = [f"fixture://run?count=1&latency_ms=0&link={i}" for i in range(198)]
            urls.append("not a url at all")
            # A binary asset, not a page — still genuinely unsupported even
            # after P7's "paste any link" Lane 3 fallback exists, since that
            # fallback explicitly declines non-page URL shapes (EV-P7-05).
            urls.append("https://example.com/totally-unsupported-file.pdf")

            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            assert resp.status_code == 202
            links = resp.json()["links"]
            assert len(links) == 200

            by_status_at_submit = [l for l in links if l["status"] == "failed"]
            assert len(by_status_at_submit) == 2
            codes = {l["failure_code"] for l in by_status_at_submit}
            assert codes == {"INVALID_URL", "UNSUPPORTED_SOURCE"}

            batch_id = resp.json()["batch_id"]
            # 200 links each land a real DuckDB commit on completion; the
            # "guaranteed flush" (jobs/engine.py's `_emit_batch_progress`)
            # measured 4-12s per drain under real machine memory pressure
            # (30 real Chrome tabs, <1.2GB free) — 15s was tight enough to
            # flake on load alone even though every link finished in ~6s.
            # `slow` tag matches (EV-P4-03's same reasoning, scripts/eval.py).
            final = await wait_for_batch_done(client, project_id, batch_id, timeout=60)
            assert final["counts"].get("done") == 198
            assert final["counts"].get("failed") == 2


@eval_case(
    "EV-P0-11",
    proves="An over-limit batch is refused with a stated limit, never silently truncated",
    source="C§12.8",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_11():
    async with temp_project("p0-11") as (settings, resolver, project_id):
        async with api_client(settings) as client:
            over_limit = settings.max_batch_links + 1
            urls = [f"fixture://run?count=1&link={i}" for i in range(over_limit)]
            resp = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            assert resp.status_code == 422
            assert str(settings.max_batch_links) in resp.text

            batches = (await client.get(f"/projects/{project_id}")).status_code
            assert batches == 200  # project itself is untouched by the rejected batch
