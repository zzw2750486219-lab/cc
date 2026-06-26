from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anthropic

from shared.models import AgentConfig

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant with access to tools. "
    "Use tools when needed to complete tasks. "
    "When you have finished the task, respond with a text summary."
)


@dataclass
class LLMResponse:
    content: list[dict[str, Any]]
    stop_reason: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    def __init__(self, config: AgentConfig) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._model = config.model

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        resp = await self._client.messages.create(**kwargs)
        content = _blocks_to_dicts(resp.content)

        return LLMResponse(
            content=content,
            stop_reason=resp.stop_reason,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )


def _blocks_to_dicts(blocks: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for block in blocks:
        d: dict[str, Any] = {"type": block.type}
        if block.type == "text":
            d["text"] = block.text
        elif block.type == "tool_use":
            d["id"] = block.id
            d["name"] = block.name
            d["input"] = block.input
        result.append(d)
    return result
