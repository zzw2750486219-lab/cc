from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("agent-platform.orchestrator")


class TaskQueue:
    """Async task queue for orchestrator workers."""

    def __init__(self, maxsize: int = 0):
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._pending: set[str] = set()

    async def enqueue(self, task_payload: dict[str, Any]) -> None:
        task_id = task_payload["id"]
        self._pending.add(task_id)
        await self._queue.put(task_payload)
        logger.info("enqueued task id=%s", task_id)

    async def dequeue(self) -> dict[str, Any]:
        payload = await self._queue.get()
        logger.info("dequeued task id=%s", payload.get("id"))
        return payload

    def task_done(self, task_id: str) -> None:
        self._pending.discard(task_id)
        self._queue.task_done()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()
