from __future__ import annotations

import pytest

from agent_core.compaction import CompactionPipeline


class TestCompactionPipeline:
    @pytest.fixture
    def pipeline(self):
        return CompactionPipeline(budget_tokens=100)

    # --- needs_compaction ---

    def test_needs_compaction_false_when_under_budget(self, pipeline):
        msgs = [{"role": "user", "content": "hello"}]
        assert pipeline.needs_compaction(msgs) is False

    def test_needs_compaction_true_when_over_budget(self):
        pipeline = CompactionPipeline(budget_tokens=1)
        msgs = [{"role": "user", "content": "x" * 100}]
        assert pipeline.needs_compaction(msgs) is True

    # --- _estimate_tokens ---

    def test_estimate_tokens_string_content(self, pipeline):
        msgs = [{"role": "user", "content": "abcd"}]
        assert pipeline._estimate_tokens(msgs) == 1

    def test_estimate_tokens_list_content(self, pipeline):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "a" * 80}]}]
        assert pipeline._estimate_tokens(msgs) == 20

    def test_estimate_tokens_tool_input(self, pipeline):
        msgs = [{"role": "assistant", "content": [{"type": "tool_use", "input": {"key": "x" * 40}}]}]
        assert pipeline._estimate_tokens(msgs) == 12

    def test_estimate_tokens_missing_content(self, pipeline):
        msgs = [{"role": "system"}]
        assert pipeline._estimate_tokens(msgs) == 0

    # --- Stage 1: _tool_result_budget ---

    def test_tool_result_budget_truncates_long_content(self, pipeline):
        msgs = [
            {"role": "user", "content": "prompt"},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "x" * 5000, "tool_use_id": "1"}
                ],
            },
        ]
        result = pipeline._tool_result_budget(msgs)
        content = result[1]["content"][0]["content"]
        assert len(content) == 4000 + len("\n... [truncated]")
        assert content.endswith("[truncated]")

    def test_tool_result_budget_leaves_short_content(self, pipeline):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "short", "tool_use_id": "1"}
                ],
            },
        ]
        result = pipeline._tool_result_budget(msgs)
        assert result[0]["content"][0]["content"] == "short"

    def test_tool_result_budget_passes_non_user_messages(self, pipeline):
        msgs = [{"role": "assistant", "content": "hello"}]
        result = pipeline._tool_result_budget(msgs)
        assert result == msgs

    def test_tool_result_budget_passes_string_content(self, pipeline):
        msgs = [{"role": "user", "content": "hello"}]
        result = pipeline._tool_result_budget(msgs)
        assert result == msgs

    # --- Stage 2: _snip_compact ---

    def test_snip_compact_keeps_last_n_turns(self, pipeline):
        msgs = [
            {"role": "user", "content": "initial prompt"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r1"}]},
            {"role": "assistant", "content": "msg1"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r2"}]},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r3"}]},
            {"role": "assistant", "content": "msg3"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r4"}]},
            {"role": "assistant", "content": "msg4"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r5"}]},
            {"role": "assistant", "content": "msg5"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r6"}]},
            {"role": "assistant", "content": "msg6"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r7"}]},
            {"role": "assistant", "content": "msg7"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r8"}]},
            {"role": "assistant", "content": "msg8"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r9"}]},
            {"role": "assistant", "content": "msg9"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r10"}]},
            {"role": "assistant", "content": "msg10"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r11"}]},
        ]
        # 11 tool turns, SNIP_TURNS=10 → keep last 10
        result = pipeline._snip_compact(msgs)
        assert len(result) < len(msgs)
        assert result[0] == msgs[0]  # first message preserved
        # last message is the 11th tool turn
        assert result[-1] == msgs[-1]

    def test_snip_compact_no_op_when_under_limit(self, pipeline):
        msgs = [
            {"role": "user", "content": "prompt"},
            {"role": "user", "content": [{"type": "tool_result", "content": "r1"}]},
        ]
        result = pipeline._snip_compact(msgs)
        assert result == msgs

    # --- Stage 3: _micro_compact ---

    def test_micro_compact_keeps_last_4_plus_summary(self, pipeline):
        msgs = [
            {"role": "user", "content": "m1"},
            {"role": "assistant", "content": "m2"},
            {"role": "user", "content": "m3"},
            {"role": "assistant", "content": "m4"},
            {"role": "user", "content": "m5"},
            {"role": "assistant", "content": "m6"},
        ]
        result = pipeline._micro_compact(msgs)
        assert len(result) == 5  # summary + last 4
        assert "summary" not in result[0].get("role", "")  # first is a user message with summary text
        assert result[1:] == msgs[-4:]

    def test_micro_compact_no_op_when_4_or_fewer(self, pipeline):
        msgs = [{"role": "user", "content": "m1"}]
        result = pipeline._micro_compact(msgs)
        assert result == msgs

    # --- Stage 4: _full_compact ---

    def test_full_compact_collapses_to_single_message(self, pipeline):
        msgs = [
            {"role": "user", "content": "original prompt"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": [{"type": "tool_result", "content": "result"}]},
        ]
        result = pipeline._full_compact(msgs)
        assert len(result) == 1
        assert "original prompt" in result[0]["content"]

    def test_full_compact_empty_messages(self, pipeline):
        result = pipeline._full_compact([])
        assert len(result) == 1
        assert result[0]["role"] == "user"

    # --- compact pipeline integration ---

    def test_compact_no_op_when_under_budget(self, pipeline):
        msgs = [{"role": "user", "content": "short"}]
        result = pipeline.compact(msgs)
        assert result == msgs

    def test_compact_applies_stages_in_order(self):
        pipeline = CompactionPipeline(budget_tokens=1)
        msgs = [{"role": "user", "content": "x" * 400}]
        result = pipeline.compact(msgs)
        assert len(result) == 1
        assert "compacted" in result[0]["content"].lower()
