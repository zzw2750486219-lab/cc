from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
