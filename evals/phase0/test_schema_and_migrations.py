"""EV-P0-12, 13 — the A§8 schema is exact, and migrations stay portable
(no INSERT OR REPLACE — A§14.2, the SQLite→Postgres door)."""

from __future__ import annotations

import re

from evals.harness import REPO_ROOT, temp_project
from evals.registry import eval_case

_A8_COLUMNS = [
    "doc_id", "project_id", "batch_id", "source", "doc_type", "source_url", "subject",
    "product_id", "variant", "captured_at", "authored_at", "author_hash", "text", "lang",
    "rating", "verified_purchase", "engagement", "parent_id", "lane", "extractor_version", "raw",
]
_NULLABLE_NO_DEFAULT = {"authored_at", "rating", "verified_purchase"}
_NOT_NULL_PROVENANCE = {"lane", "extractor_version"}


@eval_case(
    "EV-P0-12",
    proves="The documents DDL matches the A§8 schema field-for-field",
    source="A§8",
    severity="BLOCKER",
    tags=["phase:P0"],
)
async def ev_p0_12():
    from app.store import duckdb as dk

    async with temp_project("p0-12") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        reader = await dk.get_reader(project_dir)
        described = reader.execute("DESCRIBE documents").fetchall()
        columns = {row[0]: row for row in described}  # name -> (name, type, null, key, default, extra)

        assert set(columns) == set(_A8_COLUMNS), (
            f"schema mismatch: got {sorted(columns)}, want {sorted(_A8_COLUMNS)}"
        )
        for col in _NOT_NULL_PROVENANCE:
            null_ok = columns[col][2]  # DuckDB DESCRIBE 'null' column: 'YES'/'NO'
            assert null_ok == "NO", f"{col} must be NOT NULL"
        for col in _NULLABLE_NO_DEFAULT:
            null_ok = columns[col][2]
            default = columns[col][4]
            assert null_ok == "YES", f"{col} must be nullable"
            assert default is None, f"{col} must have no default (got {default!r})"


@eval_case(
    "EV-P0-13",
    proves="Migrations stay portable: a fresh DB reaches head schema_version, and none uses INSERT OR REPLACE",
    source="A§14.2",
    severity="MAJOR",
    tags=["phase:P0"],
)
async def ev_p0_13():
    migrations_root = REPO_ROOT / "backend" / "app" / "store" / "migrations"
    hits = []
    for sql_file in migrations_root.rglob("*.sql"):
        # Strip `--` comments first — the migrations' own prose explains
        # this exact rule, which would otherwise self-trigger the check.
        code_only = "\n".join(line.split("--", 1)[0] for line in sql_file.read_text(encoding="utf-8").splitlines())
        if re.search(r"INSERT\s+OR\s+REPLACE", code_only, re.IGNORECASE):
            hits.append(str(sql_file))
    assert not hits, f"INSERT OR REPLACE found in a migration (breaks the Postgres door): {hits}"

    from app.store import duckdb as dk
    from app.store import sqlite as sq

    async with temp_project("p0-13") as (settings, resolver, project_id):
        project_dir = resolver.project_dir(project_id)
        expected_ops_version = len(list((migrations_root / "ops").glob("*.sql")))
        async with sq.ops_db(project_dir) as ops_conn:
            row = await (await ops_conn.execute("SELECT version FROM schema_version")).fetchone()
        assert row["version"] == expected_ops_version

        reader = await dk.get_reader(project_dir)
        expected_wh_version = len(list((migrations_root / "warehouse").glob("*.sql")))
        wh_version = reader.execute("SELECT version FROM schema_version").fetchone()[0]
        assert wh_version == expected_wh_version
