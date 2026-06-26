from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from shared.models import Task, TaskStatus


class TestTaskStore:
    @pytest.fixture
    def store(self):
        from api.routes.tasks import TaskStore
        return TaskStore()

    @pytest.mark.asyncio
    async def test_create_task(self, store):
        task = Task(prompt="hello")
        created = await store.create(task)
        assert created.id == task.id
        assert created.prompt == "hello"

    @pytest.mark.asyncio
    async def test_create_task_emits_event(self, store):
        task = Task(prompt="hello")
        await store.create(task)

        q = await store.get_event_queue(task.id)
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event["event"] == "task.created"
        assert event["data"]["prompt"] == "hello"

    @pytest.mark.asyncio
    async def test_get_task(self, store):
        task = Task(prompt="hello")
        await store.create(task)

        retrieved = await store.get(task.id)
        assert retrieved is not None
        assert retrieved.prompt == "hello"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, store):
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all_tasks(self, store):
        t1 = Task(prompt="a", project_id="p1")
        t2 = Task(prompt="b", project_id="p2")
        await store.create(t1)
        await store.create(t2)

        tasks = await store.list_all()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_list_filter_by_project(self, store):
        t1 = Task(prompt="a", project_id="p1")
        t2 = Task(prompt="b", project_id="p2")
        await store.create(t1)
        await store.create(t2)

        tasks = await store.list_all(project_id="p1")
        assert len(tasks) == 1
        assert tasks[0].prompt == "a"

    @pytest.mark.asyncio
    async def test_update_task(self, store):
        task = Task(prompt="hello")
        await store.create(task)

        updated = await store.update(task.id, status=TaskStatus.RUNNING, num_turns=5)
        assert updated.status == TaskStatus.RUNNING
        assert updated.num_turns == 5

    @pytest.mark.asyncio
    async def test_update_nonexistent_task(self, store):
        with pytest.raises(KeyError):
            await store.update("nonexistent", status=TaskStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_update_ignores_unknown_fields(self, store):
        task = Task(prompt="hello")
        await store.create(task)

        updated = await store.update(task.id, unknown_field="value")
        assert not hasattr(updated, "unknown_field")

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self, store):
        task = Task(prompt="hello", status=TaskStatus.PENDING)
        await store.create(task)

        cancelled = await store.cancel(task.id)
        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, store):
        task = Task(prompt="hello", status=TaskStatus.RUNNING)
        await store.create(task)

        cancelled = await store.cancel(task.id)
        assert cancelled.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_task_noop(self, store):
        task = Task(prompt="hello", status=TaskStatus.COMPLETED)
        await store.create(task)

        result = await store.cancel(task.id)
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, store):
        result = await store.cancel("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_emits_event(self, store):
        task = Task(prompt="hello", status=TaskStatus.PENDING)
        await store.create(task)

        await store.cancel(task.id)

        q = await store.get_event_queue(task.id)
        events = []
        while not q.empty():
            events.append(await q.get())

        cancelled_events = [e for e in events if e["event"] == "task.cancelled"]
        assert len(cancelled_events) == 1

    @pytest.mark.asyncio
    async def test_push_event_non_existent_queue(self, store):
        """_push_event should not raise when queue doesn't exist."""
        await store._push_event("no-task", "test.event", {})


class TestTaskAPI:
    """Integration tests against the FastAPI app."""

    @pytest.fixture
    def _reset_store(self):
        from api.routes import tasks
        from api.routes.tasks import TaskStore
        tasks.store = TaskStore()

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_create_task_api(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/tasks", json={"prompt": "hello"})
            assert resp.status_code == 201
            data = resp.json()
            assert data["prompt"] == "hello"
            assert data["status"] == "pending"
            assert "id" in data

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_create_task_with_all_fields(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/tasks", json={
                "prompt": "complex task",
                "project_id": "proj-x",
                "model": "claude-opus-4-7",
                "max_turns": 10,
                "tool_whitelist": ["bash"],
                "webhook_url": "https://hooks.example.com/cb",
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["project_id"] == "proj-x"
            assert data["model"] == "claude-opus-4-7"
            assert data["max_turns"] == 10
            assert data["tool_whitelist"] == ["bash"]
            assert data["webhook_url"] == "https://hooks.example.com/cb"

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_list_tasks(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/tasks", json={"prompt": "task1"})
            await client.post("/api/v1/tasks", json={"prompt": "task2"})

            resp = await client.get("/api/v1/tasks")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_project(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/tasks", json={"prompt": "a", "project_id": "p1"})
            await client.post("/api/v1/tasks", json={"prompt": "b", "project_id": "p2"})

            resp = await client.get("/api/v1/tasks?project_id=p1")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["prompt"] == "a"

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_get_task(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/tasks", json={"prompt": "hello"})
            task_id = created.json()["id"]

            resp = await client.get(f"/api/v1/tasks/{task_id}")
            assert resp.status_code == 200
            assert resp.json()["prompt"] == "hello"

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/tasks/nonexistent")
            assert resp.status_code == 404

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_cancel_task(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/tasks", json={"prompt": "hello"})
            task_id = created.json()["id"]

            resp = await client.post(f"/api/v1/tasks/{task_id}/cancel")
            assert resp.status_code == 200
            assert resp.json()["status"] == "cancelled"

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_cancel_task_not_found(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/tasks/nonexistent/cancel")
            assert resp.status_code == 404

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_stream_task(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            created = await client.post("/api/v1/tasks", json={"prompt": "hello"})
            task_id = created.json()["id"]

            # Mark task as completed so stream ends
            from api.routes.tasks import store
            await store.update(task_id, status=TaskStatus.COMPLETED)

            async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as resp:
                assert resp.status_code == 200
                # Read one chunk
                chunk = await resp.aiter_lines().__anext__()
                assert "task.created" in chunk or "data:" in chunk

    @pytest.mark.usefixtures("_reset_store")
    @pytest.mark.asyncio
    async def test_stream_task_not_found(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/tasks/nonexistent/stream")
            assert resp.status_code == 404
