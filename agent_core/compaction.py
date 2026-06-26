from __future__ import annotations

from typing import Any

TOOL_RESULT_BUDGET_CHARS = 4000
SNIP_TURNS = 10
ESTIMATED_CHARS_PER_TOKEN = 4


class CompactionPipeline:
    def __init__(self, budget_tokens: int = 100_000) -> None:
        self.budget_tokens = budget_tokens

    def needs_compaction(self, messages: list[dict[str, Any]]) -> bool:
        return self._estimate_tokens(messages) > self.budget_tokens

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msgs = messages
        if self._estimate_tokens(msgs) <= self.budget_tokens:
            return msgs
        msgs = self._tool_result_budget(msgs)
        if self._estimate_tokens(msgs) <= self.budget_tokens:
            return msgs
        msgs = self._snip_compact(msgs)
        if self._estimate_tokens(msgs) <= self.budget_tokens:
            return msgs
        msgs = self._micro_compact(msgs)
        if self._estimate_tokens(msgs) <= self.budget_tokens:
            return msgs
        return self._full_compact(msgs)

    # ------------------------------------------------------------------
    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block.get("text", block.get("input", ""))))
        return total // ESTIMATED_CHARS_PER_TOKEN

    # ------------------------------------------------------------------
    # Stage 1: cap individual tool_result content
    def _tool_result_budget(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") != "user":
                result.append(m)
                continue
            content = m.get("content")
            if not isinstance(content, list):
                result.append(m)
                continue
            new_blocks: list[dict[str, Any]] = []
            for block in content:
                if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                    text = block["content"]
                    if len(text) > TOOL_RESULT_BUDGET_CHARS:
                        text = text[:TOOL_RESULT_BUDGET_CHARS] + "\n... [truncated]"
                    new_blocks.append({**block, "content": text})
                else:
                    new_blocks.append(block)
            result.append({**m, "content": new_blocks})
        return result

    # Stage 2: keep only the last N tool turns
    def _snip_compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tool_turns: list[int] = []
        for i, m in enumerate(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                for block in m["content"]:
                    if block.get("type") == "tool_result":
                        tool_turns.append(i)
                        break

        if len(tool_turns) <= SNIP_TURNS:
            return messages

        cutoff = tool_turns[-SNIP_TURNS]
        prefix = messages[:1]
        return prefix + messages[cutoff:]

    # Stage 3: summarise older turns into a synthetic system message
    def _micro_compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(messages) <= 4:
            return messages
        keep = messages[-4:]
        summary = (
            "Earlier in the conversation, the agent executed several tools including "
            "bash commands and file operations to work on the task."
        )
        summary_msg: dict[str, Any] = {"role": "user", "content": summary}
        return [summary_msg, *keep]

    # Stage 4: collapse entire history into a single summary
    def _full_compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        first = messages[0] if messages else {"role": "user", "content": ""}
        summary = (
            "The conversation has been compacted. The original request was: "
            + str(first.get("content", ""))
        )
        return [{"role": "user", "content": summary}]
