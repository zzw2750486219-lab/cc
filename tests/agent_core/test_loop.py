from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_core.compaction import CompactionPipeline
from agent_core.hooks import HookRegistry, HookPoint
from agent_core.llm.client import LLMClient, LLMResponse
from agent_core.loop import INITIAL_MAX_TOKENS, AgentLoop
from agent_core.tools.registry import ToolRegistry
from shared.models import AgentConfig, TaskResult


class TestAgentLoop:
    @pytest.fixture
    def config(self):
        return AgentConfig(
            task_id="t1",
            prompt="say hello",
            model="claude-sonnet-4-6-20251101",
            max_turns=5,
        )

    @pytest.fixture
    def tool_registry(self):
        return ToolRegistry()

    @pytest.fixture
    def hook_registry(self):
        return HookRegistry()

    @pytest.fixture
    def compaction(self):
        return CompactionPipeline()

    def _make_llm_response(self, text="hello", stop_reason="end_turn"):
        """Helper to create LLMResponse dicts."""
        return LLMResponse(
            content=[{"type": "text", "text": text}],
            stop_reason=stop_reason,
            input_tokens=10,
            output_tokens=5,
        )

    @pytest.mark.asyncio
    async def test_simple_text_response(self, config, tool_registry, hook_registry, compaction):
        """Agent stops on end_turn with no tool_use."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat = AsyncMock(return_value=self._make_llm_response("done", "end_turn"))

        loop = AgentLoop(config, tool_registry, hook_registry, compaction, mock_llm)
        result = await loop.run()

        assert isinstance(result, TaskResult)
        assert result.task_id == "t1"
        assert result.success is True
        assert result.summary == "done"
        assert result.num_turns == 0
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_on_max_turns(self, config, tool_registry, hook_registry, compaction):
        """Agent stops after max_turns iterations."""
        mock_llm = MagicMock(spec=LLMClient)
        # Each response has a tool_use → loop continues
        mock_llm.chat = AsyncMock(return_value=LLMResponse(
            content=[
                {"type": "text", "text": "thinking"},
                {"type": "tool_use", "id": "t1", "name": "echo", "input": {}},
            ],
            stop_reason="tool_use",
            input_tokens=10,
            output_tokens=5,
        ))

        async def _echo(args, context):
            return "ok"

        tool_registry.register("echo", {"name": "echo"}, _echo)

        config.max_turns = 3
        loop = AgentLoop(config, tool_registry, hook_registry, compaction, mock_llm)
        result = await loop.run()

        assert result.num_turns == 3
        assert mock_llm.chat.await_count == 3

    @pytest.mark.asyncio
    async def test_tool_dispatch_in_loop(self, config, hook_registry, compaction):
        """Agent dispatches tool calls and passes results back."""
        mock_llm = MagicMock(spec=LLMClient)

        call_count = [0]
        responses = [
            LLMResponse(
                content=[
                    {"type": "tool_use", "id": "t1", "name": "add", "input": {"a": 1, "b": 2}},
                ],
                stop_reason="tool_use",
                input_tokens=10,
                output_tokens=5,
            ),
            LLMResponse(
                content=[{"type": "text", "text": "result is 3"}],
                stop_reason="end_turn",
                input_tokens=20,
                output_tokens=5,
            ),
        ]

        async def _chat(**kw):
            r = responses[call_count[0]]
            call_count[0] += 1
            return r

        mock_llm.chat = _chat

        tool_registry = ToolRegistry()

        async def _add(args, ctx):
            return str(args["a"] + args["b"])

        tool_registry.register("add", {"name": "add"}, _add)

        loop = AgentLoop(config, tool_registry, hook_registry, compaction, mock_llm)
        result = await loop.run()

        assert result.success is True
        assert result.summary == "result is 3"
        assert result.num_turns == 1

    @pytest.mark.asyncio
    async def test_before_llm_call_hook_modifies_messages(self, config, tool_registry, compaction):
        """Hook can modify messages before LLM call."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat = AsyncMock(return_value=self._make_llm_response("ok"))

        hooks = HookRegistry()

        async def inject_hook(**kw):
            messages = kw["messages"]
            messages.append({"role": "user", "content": "injected"})
            return messages

        hooks.register(HookPoint.BEFORE_LLM_CALL, inject_hook)

        loop = AgentLoop(config, tool_registry, hooks, compaction, mock_llm)
        await loop.run()

        call_args = mock_llm.chat.await_args
        messages = call_args.kwargs["messages"]
        assert any(m.get("content") == "injected" for m in messages)

    @pytest.mark.asyncio
    async def test_on_error_hook_called_on_api_error(self, config, tool_registry, compaction):
        """ON_ERROR hook fires on API errors."""
        import anthropic

        mock_llm = MagicMock(spec=LLMClient)
        error = anthropic.APIStatusError("server error", response=MagicMock(), body={})
        error.status_code = 500
        error.body = {"error": {"message": "internal error"}}
        mock_llm.chat = AsyncMock(side_effect=error)

        hooks = HookRegistry()
        error_data: dict[str, object] = {}

        async def on_error(**kw):
            error_data["error"] = str(kw.get("error"))
            error_data["turn"] = kw.get("turn")

        hooks.register(HookPoint.ON_ERROR, on_error)

        loop = AgentLoop(config, tool_registry, hooks, compaction, mock_llm)
        result = await loop.run()

        assert result.success is False
        assert "server error" in error_data.get("error", "")
        assert error_data.get("turn") == 0

    @pytest.mark.asyncio
    async def test_generic_exception_handling(self, config, tool_registry, hook_registry, compaction):
        """Non-API exceptions are caught and returned as failed result."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("something broke"))

        loop = AgentLoop(config, tool_registry, hook_registry, compaction, mock_llm)
        result = await loop.run()

        assert result.success is False
        assert "something broke" in result.error

    @pytest.mark.asyncio
    async def test_on_task_complete_hook_modifies_result(self, config, tool_registry, compaction):
        """ON_TASK_COMPLETE hook can override the result."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat = AsyncMock(return_value=self._make_llm_response("done"))

        hooks = HookRegistry()

        async def complete_hook(**kw):
            result = kw["result"]
            result.summary = "overridden"
            return result

        hooks.register(HookPoint.ON_TASK_COMPLETE, complete_hook)

        loop = AgentLoop(config, tool_registry, hooks, compaction, mock_llm)
        result = await loop.run()

        assert result.summary == "overridden"

    @pytest.mark.asyncio
    async def test_before_stop_hook(self, config, tool_registry, compaction):
        """BEFORE_STOP hook is called when stop_reason is end_turn."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat = AsyncMock(return_value=self._make_llm_response("done", "end_turn"))

        hooks = HookRegistry()
        stop_data = {}

        async def before_stop(**kw):
            stop_data["reason"] = kw.get("reason")

        hooks.register(HookPoint.BEFORE_STOP, before_stop)

        loop = AgentLoop(config, tool_registry, hooks, compaction, mock_llm)
        await loop.run()

        assert stop_data.get("reason") == "end_turn"

    @pytest.mark.asyncio
    async def test_no_tool_blocks_triggers_stop(self, config, tool_registry, hook_registry, compaction):
        """When response has no tool_use blocks, agent stops even if stop_reason isn't end_turn."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat = AsyncMock(return_value=LLMResponse(
            content=[{"type": "text", "text": "done"}],
            stop_reason="max_tokens",
            input_tokens=10,
            output_tokens=5,
        ))

        loop = AgentLoop(config, tool_registry, hook_registry, compaction, mock_llm)
        result = await loop.run()

        assert result.success is True
        assert result.num_turns == 0
