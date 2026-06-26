from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger("agent-platform.cron")


class CronJob:
    def __init__(self, name: str, interval: float, fn: Callable[[], Awaitable[None]]):
        self.name = name
        self.interval = interval
        self._fn = fn
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        async def _loop():
            while True:
                try:
                    await self._fn()
                except Exception:
                    logger.exception("cron job %s failed", self.name)
                await asyncio.sleep(self.interval)

        self._task = asyncio.create_task(_loop())
        logger.info("cron job %s started interval=%.0fs", self.name, self.interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


async def stale_task_cleanup(task_store, max_age: float = 3600) -> None:
    from shared.models import TaskStatus

    removable = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    stale_ids: list[str] = []
    for task_id, task in list(task_store._tasks.items()):
        if task.status in removable:
            stale_ids.append(task_id)

    for task_id in stale_ids:
        del task_store._tasks[task_id]
        events = getattr(task_store, "_events", None)
        if events and task_id in events:
            del events[task_id]

    if stale_ids:
        logger.info("cleanup: removed %d stale tasks", len(stale_ids))
