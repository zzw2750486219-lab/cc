from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_core.llm.client import DEFAULT_SYSTEM_PROMPT, LLMClient, LLMResponse, _blocks_to_dicts
from shared.models import AgentConfig


class TestBlocksToDicts:
    def test_text_block(self):
        block = type("Block", (), {"type": "text", "text": "hello"})()

        result = _blocks_to_dicts([block])
        assert result == [{"type": "text", "text": "hello"}]

    def test_tool_use_block(self):
        block = type("Block", (), {"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "ls"}})()

        result = _blocks_to_dicts([block])
        assert result == [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "ls"}}]

    def test_mixed_blocks(self):
        text = type("Block", (), {"type": "text", "text": "hi"})()
        tool = type("Block", (), {"type": "tool_use", "id": "t1", "name": "read", "input": {}})()

        result = _blocks_to_dicts([text, tool])
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "tool_use"


class TestLLMClient:
    @pytest.fixture
    def config(self):
        return AgentConfig(
            task_id="t1",
            prompt="test",
            llm_api_key="sk-test",
            llm_base_url="https://api.test.com",
            model="claude-sonnet-4-6-20251101",
        )

    def test_model_property(self, config):
        client = LLMClient(config)
        assert client.model == "claude-sonnet-4-6-20251101"

    def test_set_model(self, config):
        client = LLMClient(config)
        client.set_model("claude-opus-4-7")
        assert client.model == "claude-opus-4-7"

    def test_default_system_prompt(self):
        assert "helpful AI assistant" in DEFAULT_SYSTEM_PROMPT


class TestLLMResponse:
    def test_dataclass(self):
        r = LLMResponse(
            content=[{"type": "text", "text": "hi"}],
            stop_reason="end_turn",
            input_tokens=10,
            output_tokens=5,
        )
        assert r.stop_reason == "end_turn"
        assert r.input_tokens == 10
        assert r.output_tokens == 5


class TestLLMClientChat:
    @pytest.fixture
    def config(self):
        return AgentConfig(
            task_id="t1",
            prompt="test",
            llm_api_key="sk-test",
            llm_base_url="https://api.test.com",
            model="claude-sonnet-4-6-20251101",
        )

    def _make_text_block(self, text="hello"):
        return type("TextBlock", (), {"type": "text", "text": text, "model_dump": lambda self: {"type": "text", "text": text}})()

    def _make_tool_use_block(self, id_="t1", name="bash", input_=None):
        if input_ is None:
            input_ = {"command": "ls"}
        return type("ToolUseBlock", (), {
            "type": "tool_use", "id": id_, "name": name, "input": input_,
            "model_dump": lambda self: {"type": "tool_use", "id": id_, "name": name, "input": input_},
        })()

    def _make_usage(self, input_tokens=100, output_tokens=50):
        return type("Usage", (), {"input_tokens": input_tokens, "output_tokens": output_tokens})()

    def _mock_response(self, content, stop_reason="end_turn", input_tokens=100, output_tokens=50):
        resp = MagicMock()
        resp.content = content
        resp.stop_reason = stop_reason
        resp.usage = self._make_usage(input_tokens, output_tokens)
        return resp

    @pytest.mark.asyncio
    async def test_chat_returns_llm_response(self, config):
        """chat() calls the SDK and returns a typed LLMResponse."""
        text_block = self._make_text_block("hello world")
        resp = self._mock_response([text_block], "end_turn", 10, 5)

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            result = await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "bash", "description": "run commands"}],
                system="You are helpful",
                max_tokens=2048,
            )

        assert isinstance(result, LLMResponse)
        assert result.content == [{"type": "text", "text": "hello world"}]
        assert result.stop_reason == "end_turn"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_chat_passes_system_when_provided(self, config):
        """When system is non-empty, it's passed to the API call."""
        text_block = self._make_text_block("ok")
        resp = self._mock_response([text_block])

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            await client.chat(
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                system="do as I say",
            )

        call_kwargs = instance.messages.create.await_args.kwargs
        assert call_kwargs["system"] == "do as I say"

    @pytest.mark.asyncio
    async def test_chat_omits_system_when_empty(self, config):
        """When system is empty string, it's not included in kwargs."""
        text_block = self._make_text_block("ok")
        resp = self._mock_response([text_block])

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            await client.chat(
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                system="",
            )

        call_kwargs = instance.messages.create.await_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_chat_omits_tools_when_empty(self, config):
        """When tools list is empty, it's not included in kwargs."""
        text_block = self._make_text_block("ok")
        resp = self._mock_response([text_block])

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            await client.chat(
                messages=[{"role": "user", "content": "x"}],
                tools=[],
            )

        call_kwargs = instance.messages.create.await_args.kwargs
        assert "tools" not in call_kwargs

    @pytest.mark.asyncio
    async def test_chat_passes_model_and_max_tokens(self, config):
        """chat() forwards model and max_tokens to the API."""
        text_block = self._make_text_block("ok")
        resp = self._mock_response([text_block])

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            await client.chat(
                messages=[{"role": "user", "content": "x"}],
                tools=[{"name": "bash"}],
                max_tokens=8192,
            )

        call_kwargs = instance.messages.create.await_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6-20251101"
        assert call_kwargs["max_tokens"] == 8192

    @pytest.mark.asyncio
    async def test_chat_handles_tool_use_response(self, config):
        """chat() correctly extracts tool_use blocks from the response."""
        tool_block = self._make_tool_use_block("call_1", "file_read", {"file_path": "x.txt"})
        resp = self._mock_response([tool_block], "tool_use", 20, 30)

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            result = await client.chat(
                messages=[{"role": "user", "content": "read x.txt"}],
                tools=[{"name": "file_read"}],
            )

        assert result.stop_reason == "tool_use"
        assert result.input_tokens == 20
        assert result.output_tokens == 30
        assert len(result.content) == 1
        assert result.content[0]["type"] == "tool_use"
        assert result.content[0]["name"] == "file_read"

    @pytest.mark.asyncio
    async def test_chat_handles_mixed_blocks(self, config):
        """chat() handles responses with both text and tool_use blocks."""
        text = self._make_text_block("thinking about it...")
        tool = self._make_tool_use_block("t1", "bash", {"command": "pwd"})
        resp = self._mock_response([text, tool], "tool_use", 30, 40)

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            result = await client.chat(
                messages=[{"role": "user", "content": "run pwd"}],
                tools=[{"name": "bash"}],
            )

        assert len(result.content) == 2
        assert result.content[0]["type"] == "text"
        assert result.content[1]["type"] == "tool_use"

    @pytest.mark.asyncio
    async def test_chat_forwards_messages_verbatim(self, config):
        """chat() passes messages through to the API unchanged."""
        text_block = self._make_text_block("response")
        resp = self._mock_response([text_block])
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        with patch("agent_core.llm.client.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(return_value=resp)
            client = LLMClient(config)
            await client.chat(messages=messages, tools=[])

        call_kwargs = instance.messages.create.await_args.kwargs
        assert call_kwargs["messages"] == messages
