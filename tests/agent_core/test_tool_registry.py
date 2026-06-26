from __future__ import annotations

import pytest

from agent_core.tools.registry import ToolRegistry


class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def echo_handler(self):
        async def _echo(args, context):
            return f"echo: {args.get('msg', '')}"
        return _echo

    @pytest.mark.asyncio
    async def test_register_and_dispatch(self, registry, echo_handler):
        schema = {"name": "echo", "description": "Echo tool"}
        registry.register("echo", schema, echo_handler)

        result = await registry.dispatch("echo", {"msg": "hello"}, {})
        assert result == "echo: hello"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self, registry):
        result = await registry.dispatch("nonexistent", {}, {})
        assert result == "Error: unknown tool 'nonexistent'"

    @pytest.mark.asyncio
    async def test_dispatch_handler_exception(self, registry):
        async def _failing(args, context):
            raise ValueError("boom")

        registry.register("fail", {"name": "fail"}, _failing)
        result = await registry.dispatch("fail", {}, {})
        assert "Error: tool 'fail' raised ValueError: boom" == result

    def test_get_schemas_all(self, registry):
        schema_a = {"name": "a"}
        schema_b = {"name": "b"}
        async def _h(args, ctx):
            return ""
        registry.register("a", schema_a, _h)
        registry.register("b", schema_b, _h)

        schemas = registry.get_schemas()
        assert schemas == [schema_a, schema_b]

    def test_get_schemas_whitelist(self, registry):
        schema_a = {"name": "a"}
        schema_b = {"name": "b"}
        async def _h(args, ctx):
            return ""
        registry.register("a", schema_a, _h)
        registry.register("b", schema_b, _h)

        schemas = registry.get_schemas(whitelist=["b"])
        assert schemas == [schema_b]

    def test_get_schemas_whitelist_ignores_unknown(self, registry):
        schema_a = {"name": "a"}
        async def _h(args, ctx):
            return ""
        registry.register("a", schema_a, _h)

        schemas = registry.get_schemas(whitelist=["a", "nonexistent"])
        assert schemas == [schema_a]

    def test_get_schemas_empty_whitelist(self, registry):
        async def _h(args, ctx):
            return ""
        registry.register("a", {"name": "a"}, _h)
        schemas = registry.get_schemas(whitelist=[])
        assert schemas == []

    @pytest.mark.asyncio
    async def test_context_passed_to_handler(self, registry):
        async def _ctx_check(args, context):
            return f"workspace={context.get('workspace_dir')}"

        registry.register("check", {"name": "check"}, _ctx_check)
        result = await registry.dispatch("check", {}, {"workspace_dir": "/tmp"})
        assert result == "workspace=/tmp"
