from __future__ import annotations

import asyncio

import pytest

from orchestrator.queue import TaskQueue


class TestTaskQueue:
    @pytest.fixture
    def queue(self):
        return TaskQueue()

    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self, queue):
        payload = {"id": "t1", "prompt": "hello"}
        await queue.enqueue(payload)

        result = await queue.dequeue()
        assert result["id"] == "t1"

    @pytest.mark.asyncio
    async def test_fifo_order(self, queue):
        await queue.enqueue({"id": "t1"})
        await queue.enqueue({"id": "t2"})

        r1 = await queue.dequeue()
        r2 = await queue.dequeue()
        assert r1["id"] == "t1"
        assert r2["id"] == "t2"

    @pytest.mark.asyncio
    async def test_pending_count(self, queue):
        assert queue.pending_count == 0

        await queue.enqueue({"id": "t1"})
        assert queue.pending_count == 1

        await queue.enqueue({"id": "t2"})
        assert queue.pending_count == 2

    @pytest.mark.asyncio
    async def test_task_done_reduces_pending(self, queue):
        await queue.enqueue({"id": "t1"})
        await queue.enqueue({"id": "t2"})

        await queue.dequeue()
        queue.task_done("t1")
        assert queue.pending_count == 1

        await queue.dequeue()
        queue.task_done("t2")
        assert queue.pending_count == 0

    @pytest.mark.asyncio
    async def test_queue_size(self, queue):
        assert queue.queue_size == 0

        await queue.enqueue({"id": "t1"})
        assert queue.queue_size == 1

        await queue.enqueue({"id": "t2"})
        assert queue.queue_size == 2

        await queue.dequeue()
        assert queue.queue_size == 1
