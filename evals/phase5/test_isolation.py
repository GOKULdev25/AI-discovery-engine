"""EV-P5-09 — chat cannot cross projects. Isolation was designed at the
storage layer (A§7.2 — each project owns its own ops.sqlite and
warehouse.duckdb) and assumed at the retrieval layer, never tested there
until now. Cross-project leakage in a competitive-research tool is the
worst-case product failure: a user comparing two competitors could see
one competitor's private research bleed into the other's answer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.chat.retrieval import hybrid_retrieve
from app.projects import scaffold
from app.projects.resolver import ProjectResolver
from app.store import duckdb as dk
from app.store import sqlite as sq
from evals.harness import make_settings
from evals.phase5._helpers import doc_row, seed_and_index
from evals.registry import eval_case


@eval_case(
    "EV-P5-09",
    proves="A question in project A never retrieves or cites a document from project B",
    source="A§7",
    severity="BLOCKER",
    tags=["phase:P5"],
)
async def ev_p5_09():
    sentinel_a = "SENTINEL-PROJECT-A: this exact review must never surface in project B's retrieval"
    sentinel_b = "SENTINEL-PROJECT-B: distinct review content for the other project"

    with tempfile.TemporaryDirectory(prefix="ev-p509-") as tmp:
        settings = make_settings(Path(tmp))
        resolver = ProjectResolver(settings)

        config_a = await scaffold.create_project(settings, resolver, "p509a")
        config_b = await scaffold.create_project(settings, resolver, "p509b")
        dir_a, dir_b = resolver.project_dir(config_a.id), resolver.project_dir(config_b.id)
        try:
            committer_a = await dk.get_committer(dir_a)
            committer_b = await dk.get_committer(dir_b)
            async with sq.ops_db(dir_a) as ops_a, sq.ops_db(dir_b) as ops_b:
                await seed_and_index(committer_a, ops_a, [doc_row("a1", config_a.id, sentinel_a)])
                await seed_and_index(committer_b, ops_b, [doc_row("b1", config_b.id, sentinel_b)])

                reader_b = await dk.get_reader(dir_b)
                # Ask project B using the exact wording of project A's
                # sentinel — the strongest possible lexical pull toward
                # leaking it, if isolation had any gap at all.
                evidence = await hybrid_retrieve(ops_b, reader_b, sentinel_a)

            texts = " ".join(d["text"] for d in evidence)
            doc_ids = {d["doc_id"] for d in evidence}
            assert "a1" not in doc_ids, "project B's retrieval returned project A's document"
            assert "SENTINEL-PROJECT-A" not in texts, "project A's content leaked into project B's evidence"
        finally:
            await dk.forget_committer(dir_a)
            await dk.forget_committer(dir_b)
