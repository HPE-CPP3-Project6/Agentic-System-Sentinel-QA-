from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class WsHub:
    """In-memory WebSocket broadcaster per run_id."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._seq: dict[str, int] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=5000)
        self._subs.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subs.get(run_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subs.pop(run_id, None)

    def emit(self, run_id: str, event_type: str, **payload: Any) -> dict[str, Any]:
        seq = self._seq.get(run_id, 0) + 1
        self._seq[run_id] = seq
        event = {
            "type": event_type,
            "run_id": run_id,
            "seq": seq,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **payload,
        }
        for q in list(self._subs.get(run_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def replay_after(self, run_id: str, after_seq: int) -> list[dict[str, Any]]:
        # MVP: no persistent replay buffer; client polls REST on reconnect.
        return []
