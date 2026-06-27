from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from shared.models import Task, TaskResult, TaskStatus, AgentConfig, SandboxConfig

logger = logging.getLogger("agent-platform.worker")


class OrchestratorWorker:
    """
    Worker loop: dequeue → sandbox → agent → stream → cleanup.

    Two execution modes (selected by SANDBOX_MODE env var):
      - inline (default): runs AgentLoop directly in the worker process
      - docker: creates a sandbox container, writes agent_config.json,
        executes bootstrap.py inside the container, parses the result
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
        self._llm_base_url = os.getenv("LLM_BASE_URL", os.getenv("ANTHROPIC_BASE_URL"))
        self._sandbox_mode = os.getenv("SANDBOX_MODE", "inline")
        if self._sandbox_mode == "docker":
            self._workspace_dir = "/workspace"
        else:
            default_ws = "/workspace" if os.path.isdir("/workspace") else "/tmp/workspace"
            self._workspace_dir = os.getenv("WORKSPACE_DIR", default_ws)

    async def start(self) -> None:
        logger.info("worker starting concurrency=%d mode=%s", self._concurrency, self._sandbox_mode)
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
            self._queue.task_done(task_id)
            return

        if task.status == TaskStatus.CANCELLED:
            self._queue.task_done(task_id)
            return

        await self._store.update(task_id, status=TaskStatus.RUNNING)
        await self._push_event(task_id, "task.started", {"task_id": task_id})

        sandbox_id = None

        try:
            agent_config = AgentConfig(
                task_id=task_id,
                prompt=task.prompt,
                model=task.model,
                max_turns=task.max_turns,
                tool_whitelist=task.tool_whitelist,
                llm_api_key=self._llm_api_key,
                llm_base_url=self._llm_base_url,
                workspace_dir=self._workspace_dir,
            )

            if self._sandbox_mode == "docker":
                sandbox_id = await self._create_sandbox(task)
                await self._push_event(task_id, "sandbox.created", {
                    "task_id": task_id,
                    "sandbox_id": sandbox_id[:12],
                })
                result = await self._run_agent_in_sandbox(task, agent_config, sandbox_id)
            else:
                result = await self._run_agent_inline(task, agent_config)

            workspace_files = await self._snapshot_workspace(sandbox_id)

            # Destroy sandbox before marking complete so SSE client sees the full lifecycle
            if sandbox_id:
                await self._push_event(task_id, "sandbox.destroyed", {
                    "task_id": task_id,
                    "sandbox_id": sandbox_id[:12],
                })
                await self._destroy_sandbox(sandbox_id)
                sandbox_id = None

            await self._push_event(task_id, "task.completed", result.to_dict())
            await self._store.update(
                task_id,
                status=TaskStatus.COMPLETED if result.success else TaskStatus.FAILED,
                result_summary=result.summary,
                num_turns=result.num_turns,
                cost_usd=result.cost_usd,
                error=result.error,
                workspace_files=workspace_files,
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

    # ------------------------------------------------------------------
    # Sandbox lifecycle (docker mode)
    # ------------------------------------------------------------------

    async def _create_sandbox(self, task: Task) -> str:
        from sandbox.providers.docker_provider import DockerProvider

        logger.info("creating sandbox container for task id=%s", task.id)
        provider = DockerProvider()
        config = SandboxConfig(
            timeout=task.max_turns * 120,  # rough: 2 min per turn
            network=True,  # sandbox needs egress to reach LLM API
            env_vars={"LLM_API_KEY": self._llm_api_key},
        )
        sandbox_id = await provider.create(config)
        await self._store.update(task.id, sandbox_id=sandbox_id)
        return sandbox_id

    async def _destroy_sandbox(self, sandbox_id: str) -> None:
        from sandbox.providers.docker_provider import DockerProvider

        logger.info("destroying sandbox id=%s", sandbox_id)
        provider = DockerProvider()
        await provider.destroy(sandbox_id)

    # ------------------------------------------------------------------
    # Workspace snapshot
    # ------------------------------------------------------------------

    async def _snapshot_workspace(self, sandbox_id: str | None = None) -> list[str]:
        """List workspace files. Docker mode runs find in container, inline mode walks locally."""
        try:
            if sandbox_id:
                from sandbox.providers.docker_provider import DockerProvider
                provider = DockerProvider()
                result = await provider.execute(sandbox_id, "find /workspace -type f | sort | head -50", timeout=10)
                if result.exit_code == 0:
                    return [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
            else:
                ws = self._workspace_dir
                if os.path.isdir(ws):
                    files: list[str] = []
                    for root, _, filenames in os.walk(ws):
                        for fn in filenames:
                            if ".pyc" in fn or fn.startswith("."):
                                continue
                            full = os.path.join(root, fn)
                            rel = "/workspace" + full[len(ws):]
                            files.append(rel)
                    return sorted(files)[:50]
        except Exception:
            logger.debug("workspace snapshot skipped", exc_info=True)
        return []

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------

    async def _run_agent_inline(self, task: Task, config: AgentConfig) -> TaskResult:
        """Run AgentLoop directly in the worker process."""
        from agent_core.loop import AgentLoop
        from agent_core.hooks import HookRegistry, HookPoint
        from agent_core.compaction import CompactionPipeline
        from agent_core.tools.registry import ToolRegistry
        from agent_core.llm.client import LLMClient

        from tools.core.bash import register as register_bash
        from tools.core.file_read import register as register_file_read
        from tools.core.file_write import register as register_file_write
        from tools.core.glob_search import register as register_glob_search

        llm_client = LLMClient(config)
        tool_registry = ToolRegistry()
        hook_registry = HookRegistry()
        compaction = CompactionPipeline()

        register_bash(tool_registry)
        register_file_read(tool_registry)
        register_file_write(tool_registry)
        register_glob_search(tool_registry)

        # Bridge agent tool events to SSE event queue
        async def on_tool_call(**kwargs):
            await self._push_event(task.id, "task.tool_call", {
                "task_id": task.id,
                "tool": kwargs.get("tool_name", ""),
                "args": kwargs.get("args", {}),
            })

        async def on_tool_result(**kwargs):
            await self._push_event(task.id, "task.tool_result", {
                "task_id": task.id,
                "tool": kwargs.get("tool_name", ""),
                "result": str(kwargs.get("result", "")),
            })

        hook_registry.register(HookPoint.PRE_TOOL_USE, on_tool_call)
        hook_registry.register(HookPoint.POST_TOOL_USE, on_tool_result)

        loop = AgentLoop(
            config=config,
            llm_client=llm_client,
            tool_registry=tool_registry,
            hook_registry=hook_registry,
            compaction_pipeline=compaction,
        )

        return await loop.run()

    async def _run_agent_in_sandbox(self, task: Task, config: AgentConfig, sandbox_id: str) -> TaskResult:
        """Write agent_config.json to the sandbox and execute bootstrap.py."""
        from sandbox.providers.docker_provider import DockerProvider

        provider = DockerProvider()

        config_json = json.dumps(config.to_dict())
        await provider.write_file(sandbox_id, "/home/user/agent_config.json", config_json)

        result_exec = await provider.execute(
            sandbox_id,
            "python /opt/agent/platform/bootstrap.py",
            timeout=task.max_turns * 120,
        )

        if result_exec.exit_code != 0:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=result_exec.stderr or "sandbox execution failed",
            )

        try:
            data = json.loads(result_exec.stdout)
            return TaskResult(
                task_id=data.get("task_id", task.id),
                success=data.get("success", False),
                summary=data.get("summary", ""),
                num_turns=data.get("num_turns", 0),
                cost_usd=data.get("cost_usd"),
                error=data.get("error"),
            )
        except (json.JSONDecodeError, TypeError):
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"failed to parse bootstrap output: {result_exec.stdout[:500]}",
            )

    # ------------------------------------------------------------------
    # Event bridge
    # ------------------------------------------------------------------

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


if __name__ == "__main__":
    import os
    from api.routes.tasks import TaskStore as ApiTaskStore
    from orchestrator.queue import TaskQueue

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    queue = TaskQueue()
    store = ApiTaskStore()
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    concurrency = int(os.getenv("WORKER_CONCURRENCY", "2"))

    asyncio.run(run_worker(queue, store, api_base_url, concurrency))
