"""SSE event fan-out, durably backed by the `events` table (IP§0.6,
EV-P0-08). Every event is persisted before it is pushed to any live
subscriber, so a dropped stream can reconnect and replay everything it
missed instead of losing progress.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, batch_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(batch_id, []).append(q)
        return q

    def unsubscribe(self, batch_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(batch_id)
        if subs and q in subs:
            subs.remove(q)
            if not subs:
                self._subscribers.pop(batch_id, None)

    async def publish(
        self,
        ops_conn: aiosqlite.Connection,
        batch_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = await ops_conn.execute(
            "INSERT INTO events (batch_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (batch_id, event_type, json.dumps(payload), now),
        )
        await ops_conn.commit()
        event_id = cur.lastrowid
        for q in list(self._subscribers.get(batch_id, [])):
            q.put_nowait({"id": event_id, "event": event_type, "data": payload})
        return event_id

    async def replay_since(
        self, ops_conn: aiosqlite.Connection, batch_id: str, since_id: int
    ) -> list[dict[str, Any]]:
        cur = await ops_conn.execute(
            "SELECT id, event_type, payload FROM events WHERE batch_id = ? AND id > ? ORDER BY id",
            (batch_id, since_id),
        )
        rows = await cur.fetchall()
        return [
            {"id": r["id"], "event": r["event_type"], "data": json.loads(r["payload"])}
            for r in rows
        ]


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
