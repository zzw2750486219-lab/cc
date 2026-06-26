from __future__ import annotations

from collections.abc import Callable, Awaitable
from typing import Any

Handler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[dict[str, Any], Handler]] = {}

    def register(self, name: str, schema: dict[str, Any], handler: Handler) -> None:
        self._tools[name] = (schema, handler)

    def get_schemas(self, whitelist: list[str] | None = None) -> list[dict[str, Any]]:
        names = whitelist if whitelist is not None else list(self._tools.keys())
        return [self._tools[n][0] for n in names if n in self._tools]

    async def dispatch(self, name: str, args: dict[str, Any], context: dict[str, Any]) -> str:
        entry = self._tools.get(name)
        if entry is None:
            return f"Error: unknown tool '{name}'"
        _, handler = entry
        try:
            return await handler(args, context)
        except Exception as exc:
            return f"Error: tool '{name}' raised {type(exc).__name__}: {exc}"
