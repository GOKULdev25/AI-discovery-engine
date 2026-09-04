"""EV-P2-01, 02, 04, 10 — doc_id identity, the P§8 criterion 4 no-op
re-run, author-distinguishes-dedup, and project scoping."""

from __future__ import annotations

import unicodedata

from app.pipeline.ids import compute_doc_id
from evals.harness import api_client, temp_project, wait_for_batch_done
from evals.registry import eval_case


@eval_case(
    "EV-P2-04",
    proves="doc_id is stable across runs, restarts, and Unicode normalization forms — it's the checkpoint and dedup key",
    source="A§8",
    severity="BLOCKER",
    tags=["phase:P2"],
)
def ev_p2_04():
    text_nfc = unicodedata.normalize("NFC", "café review")
    text_nfd = unicodedata.normalize("NFD", "café review")  # same text, decomposed form
    assert text_nfc != text_nfd, "test setup: these must be byte-different to prove anything"

    id_from_nfc = compute_doc_id("appstore", "https://x/1", "authorhash", text_nfc)
    id_from_nfd = compute_doc_id("appstore", "https://x/1", "authorhash", text_nfd)
    assert id_from_nfc == id_from_nfd, "doc_id changed across Unicode normalization forms of the same text"

    # Stable across repeated calls (no hidden randomness / time-based salt).
    again = compute_doc_id("appstore", "https://x/1", "authorhash", text_nfc)
    assert again == id_from_nfc


@eval_case(
    "EV-P2-02",
    proves="Dedup doesn't destroy real data: identical text from different authors survives as distinct rows",
    source="A§8",
    severity="BLOCKER",
    tags=["phase:P2"],
)
def ev_p2_02():
    id_author_a = compute_doc_id("playstore", "https://x/review", "author-a-hash", "good app")
    id_author_b = compute_doc_id("playstore", "https://x/review", "author-b-hash", "good app")
    assert id_author_a != id_author_b, (
        "a thousand genuine 'good app' reviews from different authors would collapse into one (A§8)"
    )


@eval_case(
    "EV-P2-01",
    proves="Re-running an identical batch is a no-op: zero new documents, nothing re-extracted (P§8 criterion 4)",
    source="P§8",
    severity="BLOCKER",
    tags=["phase:P2"],
)
async def ev_p2_01():
    async with temp_project("p2-01") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        async with api_client(settings) as client:
            urls = [f"fixture://run?count=5&latency_ms=0&link={i}" for i in range(4)]

            resp1 = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            batch1 = resp1.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch1)

            from app.store import duckdb as dk

            reader = await dk.get_reader(project_dir)
            count_after_first = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            assert count_after_first == 20  # 4 links x 5 docs

            resp2 = await client.post(f"/projects/{project_id}/batches", json={"urls": urls})
            batch2 = resp2.json()["batch_id"]
            await wait_for_batch_done(client, project_id, batch2)

            count_after_second = reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            assert count_after_second == count_after_first, (
                f"re-running an identical batch added rows: {count_after_first} -> {count_after_second}"
            )


@eval_case(
    "EV-P2-10",
    proves="Dedup is project-scoped: the same review collected into two projects yields one row in each",
    source="A§7.2",
    severity="MAJOR",
    tags=["phase:P2"],
)
async def ev_p2_10():
    async with temp_project("p2-10-a") as (settings_a, resolver_a, project_a):
        async with temp_project("p2-10-b") as (settings_b, resolver_b, project_b):
            url = "fixture://run?count=1&latency_ms=0&link=shared"
            async with api_client(settings_a) as client_a:
                resp = await client_a.post(f"/projects/{project_a}/batches", json={"urls": [url]})
                await wait_for_batch_done(client_a, project_a, resp.json()["batch_id"])
            async with api_client(settings_b) as client_b:
                resp = await client_b.post(f"/projects/{project_b}/batches", json={"urls": [url]})
                await wait_for_batch_done(client_b, project_b, resp.json()["batch_id"])

            from app.store import duckdb as dk

            reader_a = await dk.get_reader(resolver_a.project_dir(project_a))
            reader_b = await dk.get_reader(resolver_b.project_dir(project_b))
            assert reader_a.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
            assert reader_b.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
