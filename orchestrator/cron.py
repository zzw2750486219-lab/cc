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
    count = await task_store.remove_terminal()
    if count:
        logger.info("cleanup: removed %d stale tasks", count)
