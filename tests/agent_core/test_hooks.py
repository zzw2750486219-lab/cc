from __future__ import annotations

import pytest

from agent_core.hooks import HookPoint, HookRegistry


class TestHookPoint:
    def test_all_points_exist(self):
        assert len(HookPoint) == 6
        assert HookPoint.BEFORE_LLM_CALL == "before_llm_call"
        assert HookPoint.PRE_TOOL_USE == "pre_tool_use"
        assert HookPoint.POST_TOOL_USE == "post_tool_use"
        assert HookPoint.BEFORE_STOP == "before_stop"
        assert HookPoint.ON_TASK_COMPLETE == "on_task_complete"
        assert HookPoint.ON_ERROR == "on_error"


class TestHookRegistry:
    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.mark.asyncio
    async def test_run_empty_returns_none(self, registry):
        result = await registry.run(HookPoint.BEFORE_LLM_CALL, messages=[])
        assert result is None

    @pytest.mark.asyncio
    async def test_register_and_run_callback(self, registry):
        called_with = {}

        async def cb(**kwargs):
            called_with.update(kwargs)
            return None

        registry.register(HookPoint.BEFORE_LLM_CALL, cb)
        result = await registry.run(HookPoint.BEFORE_LLM_CALL, messages=[1, 2], config="cfg")
        assert result is None
        assert called_with["messages"] == [1, 2]
        assert called_with["config"] == "cfg"

    @pytest.mark.asyncio
    async def test_short_circuit_on_first_non_none(self, registry):
        async def cb1(**kw):
            return "first"

        async def cb2(**kw):
            return "second"

        registry.register(HookPoint.BEFORE_LLM_CALL, cb1)
        registry.register(HookPoint.BEFORE_LLM_CALL, cb2)

        result = await registry.run(HookPoint.BEFORE_LLM_CALL)
        assert result == "first"

    @pytest.mark.asyncio
    async def test_multiple_callbacks_second_fires_when_first_returns_none(self, registry):
        call_order = []

        async def cb1(**kw):
            call_order.append(1)
            return None

        async def cb2(**kw):
            call_order.append(2)
            return "result"

        registry.register(HookPoint.ON_ERROR, cb1)
        registry.register(HookPoint.ON_ERROR, cb2)

        result = await registry.run(HookPoint.ON_ERROR)
        assert result == "result"
        assert call_order == [1, 2]

    @pytest.mark.asyncio
    async def test_different_hook_points_independent(self, registry):
        pre_called = False
        post_called = False

        async def pre_cb(**kw):
            nonlocal pre_called
            pre_called = True
            return None

        async def post_cb(**kw):
            nonlocal post_called
            post_called = True
            return None

        registry.register(HookPoint.PRE_TOOL_USE, pre_cb)
        registry.register(HookPoint.POST_TOOL_USE, post_cb)

        await registry.run(HookPoint.PRE_TOOL_USE)
        assert pre_called is True
        assert post_called is False

        await registry.run(HookPoint.POST_TOOL_USE)
        assert post_called is True
