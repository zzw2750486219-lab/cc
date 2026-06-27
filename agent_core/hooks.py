from __future__ import annotations

import logging
from collections.abc import Callable, Awaitable
from enum import Enum
from typing import Any

logger = logging.getLogger("agent-core.hooks")


class HookPoint(str, Enum):
    BEFORE_LLM_CALL = "before_llm_call"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    BEFORE_STOP = "before_stop"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_ERROR = "on_error"


HookCallback = Callable[..., Awaitable[Any]]


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[HookCallback]] = {p: [] for p in HookPoint}

    def register(self, point: HookPoint, callback: HookCallback) -> None:
        self._hooks[point].append(callback)

    async def run(self, point: HookPoint, **kwargs: Any) -> Any:
        for callback in self._hooks[point]:
            try:
                result = await callback(**kwargs)
            except Exception:
                logger.exception("hook callback failed point=%s", point)
                continue
            if result is not None:
                return result
        return None
