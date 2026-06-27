from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request
from starlette.responses import JSONResponse

from shared.models import Task, TaskStatus
from orchestrator.queue import TaskQueue

logger = logging.getLogger("agent-platform.api")

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
task_queue = TaskQueue()


class TaskStore:
    """In-memory task store with per-task SSE event queues."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._events: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def create(self, task: Task) -> Task:
        async with self._lock:
            self._tasks[task.id] = task
            self._events[task.id] = asyncio.Queue()
        await self._push_event(task.id, "task.created", task.to_dict())
        return task

    async def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def list_all(self, project_id: str | None = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if project_id:
            tasks = [t for t in tasks if t.project_id == project_id]
        return sorted(tasks, key=lambda t: t.id, reverse=True)

    async def update(self, task_id: str, **fields: Any) -> Task:
        task = self._tasks.get(task_id)
        if not task:
            raise KeyError(task_id)
        for k, v in fields.items():
            if hasattr(task, k):
                setattr(task, k, v)
        return task

    async def cancel(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            await self._push_event(task_id, "task.cancelled", task.to_dict())
        return task

    async def get_event_queue(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        return self._events.get(task_id)

    async def remove(self, task_id: str) -> bool:
        async with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
            if task_id in self._events:
                del self._events[task_id]
            return True
        return False

    async def remove_terminal(self) -> int:
        """Remove all COMPLETED, FAILED, or CANCELLED tasks. Returns count removed."""
        async with self._lock:
            removable = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
            stale_ids = [tid for tid, t in self._tasks.items() if t.status in removable]
            for tid in stale_ids:
                del self._tasks[tid]
                if tid in self._events:
                    del self._events[tid]
            return len(stale_ids)

    async def _push_event(self, task_id: str, event: str, data: dict[str, Any]) -> None:
        q = self._events.get(task_id)
        if q:
            await q.put({"event": event, "data": data})


store = TaskStore()


def _serialize_event(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data)}


@router.post("", status_code=201)
async def create_task(payload: dict[str, Any], request: Request):
    task = Task(
        prompt=payload["prompt"],
        project_id=payload.get("project_id", "default"),
        model=payload.get("model", "claude-sonnet-4-6-20251101"),
        max_turns=payload.get("max_turns", 50),
        tool_whitelist=payload.get("tool_whitelist"),
        webhook_url=payload.get("webhook_url"),
    )
    await store.create(task)
    await task_queue.enqueue(task.to_dict())
    logger.info("task created id=%s", task.id)
    return task.to_dict()


@router.get("")
async def list_tasks(project_id: str | None = None):
    tasks = await store.list_all(project_id)
    return [t.to_dict() for t in tasks]


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = await store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task.to_dict()


@router.get("/{task_id}/stream")
async def stream_task(task_id: str, request: Request):
    task = await store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")

    q = await store.get_event_queue(task_id)
    if not q:
        raise HTTPException(status_code=500, detail="event queue not found")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield _serialize_event(msg["event"], msg["data"])
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}

                t = await store.get(task_id)
                if t and t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    break
        except asyncio.CancelledError:
            pass

    return EventSourceResponse(event_generator())


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    task = await store.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task.to_dict()
