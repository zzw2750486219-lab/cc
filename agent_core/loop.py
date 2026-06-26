from __future__ import annotations

from typing import Any

import anthropic

from shared.models import AgentConfig, TaskResult, TaskStatus

from agent_core.hooks import HookPoint, HookRegistry
from agent_core.compaction import CompactionPipeline
from agent_core.llm.client import DEFAULT_SYSTEM_PROMPT, LLMClient, LLMResponse
from agent_core.recovery import (
    EscalateTokens,
    FallbackModel,
    NoRecovery,
    ReactiveCompact,
    Retry,
    apply_retry,
    handle_error,
)
from agent_core.tools.registry import ToolRegistry

INITIAL_MAX_TOKENS = 4096


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        hook_registry: HookRegistry,
        compaction_pipeline: CompactionPipeline,
        llm_client: LLMClient,
        system_prompt: str = "",
    ) -> None:
        self._config = config
        self._tools = tool_registry
        self._hooks = hook_registry
        self._compaction = compaction_pipeline
        self._llm = llm_client
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    async def run(self) -> TaskResult:
        config = self._config
        tools = self._tools.get_schemas(config.tool_whitelist)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": config.prompt}
        ]

        turn = 0
        current_max_tokens = INITIAL_MAX_TOKENS
        final_text = ""

        while turn < config.max_turns:
            # --- BeforeLLMCall hook ---
            hook_result = await self._hooks.run(
                HookPoint.BEFORE_LLM_CALL,
                messages=messages,
                config=config,
            )
            if hook_result is not None:
                messages = hook_result

            # --- Compaction ---
            if self._compaction.needs_compaction(messages):
                messages = self._compaction.compact(messages)

            # --- LLM call with error recovery ---
            attempt = 0
            while True:
                try:
                    response = await self._llm.chat(
                        messages=messages,
                        tools=tools,
                        system=self._system_prompt,
                        max_tokens=current_max_tokens,
                    )
                    break
                except anthropic.APIStatusError as exc:
                    action = handle_error(exc.status_code, exc.body, attempt)
                    if isinstance(action, Retry):
                        await apply_retry(action)
                        attempt += 1
                        continue
                    elif isinstance(action, FallbackModel):
                        self._llm.set_model(action.model)
                        continue
                    elif isinstance(action, EscalateTokens):
                        current_max_tokens = action.max_tokens
                        continue
                    elif isinstance(action, ReactiveCompact):
                        messages = self._compaction.compact(messages)
                        continue
                    else:
                        await self._hooks.run(
                            HookPoint.ON_ERROR,
                            error=exc,
                            turn=turn,
                        )
                        return TaskResult(
                            task_id=config.task_id,
                            success=False,
                            num_turns=turn,
                            error=str(exc),
                        )
                except Exception as exc:
                    await self._hooks.run(
                        HookPoint.ON_ERROR,
                        error=exc,
                        turn=turn,
                    )
                    return TaskResult(
                        task_id=config.task_id,
                        success=False,
                        num_turns=turn,
                        error=str(exc),
                    )

            # --- Process response ---
            text_blocks = [b for b in response.content if b["type"] == "text"]
            tool_blocks = [b for b in response.content if b["type"] == "tool_use"]

            final_text = "\n".join(b["text"] for b in text_blocks)

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn" or not tool_blocks:
                await self._hooks.run(
                    HookPoint.BEFORE_STOP,
                    reason="end_turn",
                    messages=messages,
                )
                break

            # --- Tool dispatch ---
            tool_results: list[dict[str, Any]] = []
            for tb in tool_blocks:
                ctx = {"workspace_dir": config.workspace_dir}

                pre_result = await self._hooks.run(
                    HookPoint.PRE_TOOL_USE,
                    tool_name=tb["name"],
                    args=tb["input"],
                    context=ctx,
                )
                args = pre_result if pre_result is not None else tb["input"]

                result = await self._tools.dispatch(tb["name"], args, ctx)

                post_result = await self._hooks.run(
                    HookPoint.POST_TOOL_USE,
                    tool_name=tb["name"],
                    args=args,
                    result=result,
                )
                if post_result is not None:
                    result = str(post_result)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb["id"],
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})
            turn += 1

        # --- OnTaskComplete hook ---
        result = TaskResult(
            task_id=config.task_id,
            success=True,
            summary=final_text,
            num_turns=turn,
        )

        hook_result = await self._hooks.run(
            HookPoint.ON_TASK_COMPLETE,
            result=result,
        )
        if hook_result is not None:
            result = hook_result

        return result
