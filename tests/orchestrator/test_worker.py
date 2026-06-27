from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.queue import TaskQueue
from orchestrator.worker import OrchestratorWorker
from shared.models import Task, TaskResult, TaskStatus


class MockTaskStore:
    """Minimal mock of TaskStore for worker tests."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}

    async def create(self, task: Task) -> Task:
        self._tasks[task.id] = task
        self._queues[task.id] = asyncio.Queue()
        return task

    async def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def update(self, task_id: str, **fields):
        task = self._tasks.get(task_id)
        if task:
            for k, v in fields.items():
                if hasattr(task, k):
                    setattr(task, k, v)
        return task

    async def get_event_queue(self, task_id: str):
        return self._queues.get(task_id)

    async def list_all(self, project_id=None):
        return list(self._tasks.values())


class TestOrchestratorWorker:
    @pytest.fixture
    def queue(self):
        return TaskQueue()

    @pytest.fixture
    def store(self):
        return MockTaskStore()

    @pytest.mark.asyncio
    async def test_process_completes_task(self, queue, store):
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        mock_result = TaskResult(task_id=task.id, success=True, summary="done", num_turns=3)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        with patch.object(worker, "_run_agent_inline", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            await worker._process(payload)

        updated = await store.get(task.id)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result_summary == "done"
        assert updated.num_turns == 3

    @pytest.mark.asyncio
    async def test_process_skips_cancelled_task(self, queue, store):
        task = Task(prompt="test", status=TaskStatus.CANCELLED)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        await worker._process(payload)

        updated = await store.get(task.id)
        assert updated.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_process_skips_missing_task(self, queue, store):
        payload = {"id": "nonexistent", "prompt": "test"}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        await worker._process(payload)
        # Should not raise

    @pytest.mark.asyncio
    async def test_run_agent_completes(self, queue, store):
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        from shared.models import AgentConfig

        config = AgentConfig(task_id=task.id, prompt=task.prompt, max_turns=3)

        with patch("agent_core.loop.AgentLoop.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = TaskResult(task_id=task.id, success=True, summary="done", num_turns=3)
            result = await worker._run_agent_inline(task, config)

        assert result.success is True
        assert result.num_turns == 3

    @pytest.mark.asyncio
    async def test_run_agent_stops_when_cancelled(self, queue, store):
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        await store.update(task.id, status=TaskStatus.CANCELLED)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        from shared.models import AgentConfig

        config = AgentConfig(task_id=task.id, prompt=task.prompt, max_turns=5)

        with patch("agent_core.loop.AgentLoop.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = TaskResult(task_id=task.id, success=True, summary="completed in 0 turns", num_turns=0)
            result = await worker._run_agent_inline(task, config)

        assert result.success is True
        assert result.summary == "completed in 0 turns"

    @pytest.mark.asyncio
    async def test_push_event(self, queue, store):
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        await worker._push_event(task.id, "test.event", {"key": "value"})

        q = await store.get_event_queue(task.id)
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event["event"] == "test.event"
        assert event["data"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_push_event_no_queue(self, queue, store):
        worker = OrchestratorWorker(queue, store, concurrency=1)
        # Should not raise when queue doesn't exist
        await worker._push_event("no-queue", "test.event", {})

    @pytest.mark.asyncio
    async def test_create_sandbox_returns_id(self, queue, store):
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        with patch("sandbox.providers.docker_provider.DockerProvider.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = f"container-{task.id}"
            sandbox_id = await worker._create_sandbox(task)

        assert sandbox_id == f"container-{task.id}"

        updated = await store.get(task.id)
        assert updated.sandbox_id == sandbox_id

    @pytest.mark.asyncio
    async def test_destroy_sandbox(self, queue, store):
        worker = OrchestratorWorker(queue, store, concurrency=1)
        with patch("sandbox.providers.docker_provider.DockerProvider.destroy", new_callable=AsyncMock) as mock_destroy:
            await worker._destroy_sandbox("sb-1")
            mock_destroy.assert_awaited_once_with("sb-1")

    @pytest.mark.asyncio
    async def test_run_loop_cancelled_error(self, queue, store):
        worker = OrchestratorWorker(queue, store, concurrency=1)

        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)
        await queue.enqueue({"id": task.id, "prompt": task.prompt})

        loop_task = asyncio.create_task(worker._run_loop())
        await asyncio.sleep(0.2)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_process_stores_workspace_files(self, queue, store):
        """Inline mode _process captures workspace files from snapshot."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        with patch.object(worker, "_run_agent_inline", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = TaskResult(task_id=task.id, success=True, summary="ok")
            with patch.object(worker, "_snapshot_workspace", new_callable=AsyncMock) as mock_snap:
                mock_snap.return_value = ["/workspace/a.txt", "/workspace/b.txt"]
                await worker._process(payload)

        updated = await store.get(task.id)
        assert updated.workspace_files == ["/workspace/a.txt", "/workspace/b.txt"]

    @pytest.mark.asyncio
    async def test_process_handles_exception(self, queue, store):
        """When _run_agent_inline raises, task is marked FAILED."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        with patch.object(worker, "_run_agent_inline", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("boom")
            await worker._process(payload)

        updated = await store.get(task.id)
        assert updated.status == TaskStatus.FAILED
        assert "boom" in (updated.error or "")

    @pytest.mark.asyncio
    async def test_process_pushes_failed_event_on_error(self, queue, store):
        """On error, task.failed is pushed to the event queue."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        with patch.object(worker, "_run_agent_inline", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("crash")
            await worker._process(payload)

        q = await store.get_event_queue(task.id)
        # Consume events until we find task.failed
        found = False
        while not q.empty():
            evt = q.get_nowait()
            if evt["event"] == "task.failed":
                assert "crash" in str(evt["data"].get("error", ""))
                found = True
        assert found

    @pytest.mark.asyncio
    async def test_docker_process_sandbox_events(self, queue, store):
        """Docker mode pushes sandbox.created and sandbox.destroyed events."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        worker._sandbox_mode = "docker"
        worker._workspace_dir = "/workspace"

        sb_id = "abc123def456"
        mock_result = TaskResult(task_id=task.id, success=True, summary="done", num_turns=1)

        with patch.object(worker, "_create_sandbox", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = sb_id
            with patch.object(worker, "_run_agent_in_sandbox", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = mock_result
                with patch.object(worker, "_destroy_sandbox", new_callable=AsyncMock):
                    with patch.object(worker, "_snapshot_workspace", new_callable=AsyncMock, return_value=[]):
                        await worker._process(payload)

        q = await store.get_event_queue(task.id)
        events = []
        while not q.empty():
            events.append(q.get_nowait()["event"])

        assert "sandbox.created" in events
        assert "sandbox.destroyed" in events

    @pytest.mark.asyncio
    async def test_sandbox_failure_cleans_up(self, queue, store):
        """When _run_agent_in_sandbox fails, sandbox is still destroyed in finally."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        payload = {"id": task.id, "prompt": task.prompt}
        await queue.enqueue(payload)

        worker = OrchestratorWorker(queue, store, concurrency=1)
        worker._sandbox_mode = "docker"
        worker._workspace_dir = "/workspace"

        with patch.object(worker, "_create_sandbox", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = "sb-fail"
            with patch.object(worker, "_run_agent_in_sandbox", new_callable=AsyncMock) as mock_run:
                mock_run.side_effect = RuntimeError("sandbox crash")
                with patch.object(worker, "_destroy_sandbox", new_callable=AsyncMock) as mock_destroy:
                    await worker._process(payload)
                    mock_destroy.assert_awaited()

    @pytest.mark.asyncio
    async def test_run_agent_in_sandbox_parses_tool_events(self, queue, store):
        """stdout with event lines are pushed to SSE, last line is TaskResult."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        worker = OrchestratorWorker(queue, store, concurrency=1)

        from shared.models import AgentConfig
        config = AgentConfig(task_id=task.id, prompt=task.prompt)

        stdout_lines = [
            json.dumps({"event": "task.tool_call", "data": {"tool": "bash", "args": {"command": "ls"}}}),
            json.dumps({"event": "task.tool_result", "data": {"tool": "bash", "result": "file.txt"}}),
            json.dumps({"task_id": task.id, "success": True, "summary": "done", "num_turns": 2, "cost_usd": 0.01, "error": None}),
        ]

        mock_exec = MagicMock()
        mock_exec.exit_code = 0
        mock_exec.stdout = "\n".join(stdout_lines)
        mock_exec.stderr = ""

        with patch("sandbox.providers.docker_provider.DockerProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.write_file = AsyncMock()
            instance.execute = AsyncMock(return_value=mock_exec)
            result = await worker._run_agent_in_sandbox(task, config, "sb-1")

        assert result.success is True
        assert result.summary == "done"
        assert result.num_turns == 2

    @pytest.mark.asyncio
    async def test_run_agent_in_sandbox_exit_code_nonzero(self, queue, store):
        """Non-zero exit code returns failed TaskResult with stderr."""
        task = Task(prompt="test", status=TaskStatus.PENDING)
        await store.create(task)

        worker = OrchestratorWorker(queue, store, concurrency=1)

        from shared.models import AgentConfig
        config = AgentConfig(task_id=task.id, prompt=task.prompt)

        mock_exec = MagicMock()
        mock_exec.exit_code = 1
        mock_exec.stdout = "something went wrong"
        mock_exec.stderr = "LLM authentication failed"

        with patch("sandbox.providers.docker_provider.DockerProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.write_file = AsyncMock()
            instance.execute = AsyncMock(return_value=mock_exec)
            result = await worker._run_agent_in_sandbox(task, config, "sb-1")

        assert result.success is False
        assert "LLM authentication failed" in (result.error or "")
