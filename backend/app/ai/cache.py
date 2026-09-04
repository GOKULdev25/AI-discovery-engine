"""The global LLM response cache (A§7.3, A§11.3) — `data/app.sqlite`,
keyed on content hash + prompt version, never on project. Two projects
classifying the same review (competitive research overlaps subjects
constantly) pay for it once. This is what makes P§8's "re-running doesn't
re-charge" literally true rather than aspirational (EV-P3-02).

Keying on prompt version, not just content, is deliberate (IP§3 "Watch",
closed by EV-P3-03): bump `pipeline/classify.py`'s `PROMPT_VERSION` after
any prompt change and every cached row misses cleanly — an unversioned
cache would silently keep serving decisions made under a prompt that no
longer exists.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.pipeline.ids import normalize_text_for_id


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text_for_id(text).encode("utf-8")).hexdigest()


def cache_key(text: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{content_hash(text)}|{prompt_version}".encode("utf-8")).hexdigest()


async def get(conn: aiosqlite.Connection, text: str, prompt_version: str) -> Any | None:
    key = cache_key(text, prompt_version)
    cur = await conn.execute("SELECT response_json FROM llm_cache WHERE cache_key = ?", (key,))
    row = await cur.fetchone()
    if row is None:
        return None
    return json.loads(row["response_json"])


async def put(
    conn: aiosqlite.Connection, text: str, prompt_version: str, response: Any, provider: str
) -> None:
    key = cache_key(text, prompt_version)
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        """INSERT INTO llm_cache (cache_key, response_json, provider, created_at) VALUES (?, ?, ?, ?)
           ON CONFLICT (cache_key) DO UPDATE SET
             response_json = excluded.response_json, provider = excluded.provider, created_at = excluded.created_at""",
        (key, json.dumps(response), provider, now),
    )
    await conn.commit()
