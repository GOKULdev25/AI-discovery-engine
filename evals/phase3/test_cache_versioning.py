"""EV-P3-03 — the cache is keyed on prompt version too, not just content
(IP§3 "Watch": a cache that ignores prompt changes would silently keep
serving decisions made under a prompt that no longer exists)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.ai import cache
from app.store import sqlite as sq
from evals.registry import eval_case


@eval_case(
    "EV-P3-03",
    proves="Bumping the prompt version misses the cache; not bumping hits it",
    source="IP§3",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_03():
    text = "This app crashes constantly and support never responds."
    with tempfile.TemporaryDirectory(prefix="ev-p303-") as tmp:
        app_sqlite = Path(tmp) / "app.sqlite"
        async with sq.app_db(app_sqlite) as conn:
            await cache.put(conn, text, "v1", {"decision": "keep"}, "gemini")

            same_version = await cache.get(conn, text, "v1")
            assert same_version == {"decision": "keep"}, "an unchanged prompt version must hit the cache"

            bumped_version = await cache.get(conn, text, "v2")
            assert bumped_version is None, "a bumped prompt version must miss the cache, not serve a stale decision"

            # And re-populating under the new version works normally —
            # versioning isn't a one-way lockout.
            await cache.put(conn, text, "v2", {"decision": "drop"}, "groq")
            assert await cache.get(conn, text, "v2") == {"decision": "drop"}
            assert await cache.get(conn, text, "v1") == {"decision": "keep"}, "the old version's entry must survive independently"
