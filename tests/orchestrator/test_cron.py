from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.cron import CronJob, stale_task_cleanup
from shared.models import Task, TaskStatus


class TestCronJob:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        called = 0

        async def _fn():
            nonlocal called
            called += 1

        job = CronJob("test", 0.05, _fn)
        await job.start()

        await asyncio.sleep(0.15)
        await job.stop()

        assert called >= 2

    @pytest.mark.asyncio
    async def test_handles_exception(self, caplog):
        import logging

        async def _failing():
            raise RuntimeError("cron failure")

        job = CronJob("failing", 0.05, _failing)
        with caplog.at_level(logging.ERROR, logger="agent-platform.cron"):
            await job.start()
            await asyncio.sleep(0.15)
            await job.stop()

        assert any("cron job failing failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        async def _fn():
            pass

        job = CronJob("test", 60, _fn)
        await job.start()
        assert job._task is not None
        assert not job._task.done()

        await job.stop()
        assert job._task.done()


class TestStaleTaskCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_finds_terminal_tasks(self, caplog):
        import logging

        class MockStore:
            _tasks = {}

        store = MockStore()
        store._tasks = {
            "t1": Task(prompt="a", status=TaskStatus.COMPLETED),
            "t2": Task(prompt="b", status=TaskStatus.FAILED),
            "t3": Task(prompt="c", status=TaskStatus.CANCELLED),
            "t4": Task(prompt="d", status=TaskStatus.RUNNING),
            "t5": Task(prompt="e", status=TaskStatus.PENDING),
        }

        with caplog.at_level(logging.INFO, logger="agent-platform.cron"):
            await stale_task_cleanup(store)

        assert any("removed 3 stale tasks" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_cleanup_no_terminal_tasks(self, caplog):
        import logging

        class MockStore:
            _tasks = {}

        store = MockStore()
        store._tasks = {
            "t1": Task(prompt="a", status=TaskStatus.RUNNING),
        }

        with caplog.at_level(logging.INFO, logger="agent-platform.cron"):
            await stale_task_cleanup(store)

        found = [r for r in caplog.records if "stale tasks" in r.message]
        assert len(found) == 0
