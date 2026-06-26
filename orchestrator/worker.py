from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from shared.models import Task, TaskResult, TaskStatus, AgentConfig

logger = logging.getLogger("agent-platform.worker")


class OrchestratorWorker:
    """
    Worker loop: dequeue → sandbox → agent → stream → cleanup.

    Integration points (imported at call time so modules can be loaded when ready):
      - sandbox: SandboxProvider.create / .destroy
      - agent_core: AgentLoop.run
    """

    def __init__(
        self,
        queue,
        task_store,
        api_base_url: str = "http://localhost:8000",
        concurrency: int = 2,
    ):
        self._queue = queue
        self._store = task_store
        self._api_base_url = api_base_url.rstrip("/")
        self._concurrency = concurrency
        self._tasks: set[asyncio.Task] = set()
        self._llm_api_key = os.getenv("LLM_API_KEY", "")

    async def start(self) -> None:
        logger.info("worker starting concurrency=%d", self._concurrency)
        for _ in range(self._concurrency):
            t = asyncio.create_task(self._run_loop())
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("worker stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                payload = await self._queue.dequeue()
                await self._process(payload)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("worker loop error")

    async def _process(self, payload: dict[str, Any]) -> None:
        task_id = payload["id"]
        logger.info("processing task id=%s", task_id)

        task = await self._store.get(task_id)
        if not task:
            logger.warning("task id=%s not found, skipping", task_id)
            return

        if task.status == TaskStatus.CANCELLED:
            self._queue.task_done(task_id)
            return

        await self._store.update(task_id, status=TaskStatus.RUNNING)
        await self._push_event(task_id, "task.started", {"task_id": task_id})

        sandbox_id = None
        result = TaskResult(task_id=task_id, success=False)

        try:
            sandbox_id = await self._create_sandbox(task)

            agent_config = AgentConfig(
                task_id=task_id,
                prompt=task.prompt,
                model=task.model,
                max_turns=task.max_turns,
                tool_whitelist=task.tool_whitelist,
                llm_api_key=self._llm_api_key,
            )

            result = await self._run_agent(task, agent_config)
            await self._push_event(task_id, "task.completed", result.to_dict())
            await self._store.update(
                task_id,
                status=TaskStatus.COMPLETED,
                result_summary=result.summary,
                num_turns=result.num_turns,
                cost_usd=result.cost_usd,
            )

        except asyncio.CancelledError:
            await self._store.update(task_id, status=TaskStatus.CANCELLED)
            await self._push_event(task_id, "task.cancelled", {"task_id": task_id})

        except Exception as exc:
            logger.exception("task id=%s failed", task_id)
            await self._store.update(task_id, status=TaskStatus.FAILED, error=str(exc))
            await self._push_event(task_id, "task.failed", {"task_id": task_id, "error": str(exc)})

        finally:
            if sandbox_id:
                await self._destroy_sandbox(sandbox_id)
            self._queue.task_done(task_id)

    async def _create_sandbox(self, task: Task) -> str:
        logger.info("creating sandbox for task id=%s", task.id)
        await asyncio.sleep(0.1)
        sandbox_id = f"sandbox-{task.id}"
        await self._store.update(task.id, sandbox_id=sandbox_id)
        return sandbox_id

    async def _destroy_sandbox(self, sandbox_id: str) -> None:
        logger.info("destroying sandbox id=%s", sandbox_id)

    async def _run_agent(self, task: Task, config: AgentConfig) -> TaskResult:
        turn = 0
        try:
            while turn < config.max_turns:
                cancelled = await self._store.get(task.id)
                if cancelled and cancelled.status == TaskStatus.CANCELLED:
                    raise asyncio.CancelledError()

                turn += 1
                await self._push_event(task.id, "task.turn", {"task_id": task.id, "turn": turn})

                await self._push_event(
                    task.id,
                    "task.tool_call",
                    {"task_id": task.id, "turn": turn, "tool": "read_file", "args": {}},
                )

                await asyncio.sleep(0.05)

                await self._push_event(
                    task.id,
                    "task.tool_result",
                    {"task_id": task.id, "turn": turn, "tool": "read_file", "result": ""},
                )

        except asyncio.CancelledError:
            raise

        return TaskResult(
            task_id=task.id,
            success=True,
            summary=f"completed in {turn} turns",
            num_turns=turn,
        )

    async def _push_event(self, task_id: str, event: str, data: dict[str, Any]) -> None:
        q = await self._store.get_event_queue(task_id)
        if q:
            await q.put({"event": event, "data": data})


async def run_worker(
    queue,
    store,
    api_base_url: str = "http://localhost:8000",
    concurrency: int = 2,
) -> None:
    worker = OrchestratorWorker(
        queue=queue,
        task_store=store,
        api_base_url=api_base_url,
        concurrency=concurrency,
    )
    await worker.start()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await worker.stop()
