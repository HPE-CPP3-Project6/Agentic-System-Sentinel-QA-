from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any


class WsHub:
    """In-memory WebSocket broadcaster per run_id.

    CRITICAL threading note: `emit()` is called from the worker DAEMON THREAD
    that runs the pipeline (see shim.app._enqueue), while each subscriber's
    `asyncio.Queue` belongs to the server's event loop. `asyncio.Queue` is NOT
    thread-safe — calling `put_nowait` directly from the worker thread mutates
    the queue without waking the `await q.get()` in the WS coroutine, so events
    were silently dropped and the UI fell back to slow REST polling.

    Fix: capture the running loop when a client subscribes (that happens inside
    the async WS handler) and marshal every emit onto that loop with
    `loop.call_soon_threadsafe`, which both mutates the queue AND wakes the
    waiting getter.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._seq: dict[str, int] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        # subscribe() runs inside the async WS handler → capture its loop.
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=5000)
        self._subs.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subs.get(run_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subs.pop(run_id, None)

    @staticmethod
    def _safe_put(q: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass

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
        subs = list(self._subs.get(run_id, []))
        if not subs:
            return event
        loop = self._loop
        for q in subs:
            if loop is not None and loop.is_running():
                # Worker-thread → event-loop hop: schedules the put AND wakes
                # the awaiting `q.get()` in the WS coroutine.
                loop.call_soon_threadsafe(self._safe_put, q, event)
            else:
                # Same-thread / no-loop fallback (tests, sync callers).
                self._safe_put(q, event)
        return event

    def replay_after(self, run_id: str, after_seq: int) -> list[dict[str, Any]]:
        # MVP: no persistent replay buffer; client polls REST on reconnect.
        return []
