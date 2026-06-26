from __future__ import annotations

import pytest

from agent_core.recovery import (
    EscalateTokens,
    FallbackModel,
    NoRecovery,
    ReactiveCompact,
    Retry,
    apply_retry,
    handle_error,
)


class TestRecoveryActions:
    def test_retry_stores_delay(self):
        a = Retry(3.5)
        assert a.delay == 3.5

    def test_fallback_model_stores_model(self):
        a = FallbackModel("claude-haiku-4-5-20251001")
        assert a.model == "claude-haiku-4-5-20251001"

    def test_escalate_tokens_stores_max_tokens(self):
        a = EscalateTokens(8192)
        assert a.max_tokens == 8192

    def test_reactive_compact(self):
        a = ReactiveCompact()
        assert isinstance(a, ReactiveCompact)

    def test_no_recovery(self):
        a = NoRecovery()
        assert isinstance(a, NoRecovery)


class TestHandleError:
    def test_429_first_attempt_returns_retry(self):
        action = handle_error(429, None, attempt=0)
        assert isinstance(action, Retry)
        assert 2.0 <= action.delay <= 3.0  # base 2s + random(0,1)

    def test_429_fifth_attempt_returns_retry(self):
        action = handle_error(429, None, attempt=4)
        assert isinstance(action, Retry)

    def test_429_max_retries_exceeded_returns_no_recovery(self):
        action = handle_error(429, None, attempt=5)
        assert isinstance(action, NoRecovery)

    def test_429_delay_increases_with_attempts(self):
        a1 = handle_error(429, None, attempt=0)
        a2 = handle_error(429, None, attempt=2)
        # Exponential backoff: attempt 2 should have higher base delay
        assert isinstance(a1, Retry)
        assert isinstance(a2, Retry)
        assert a2.delay > a1.delay

    def test_529_returns_fallback_model(self):
        action = handle_error(529, None)
        assert isinstance(action, FallbackModel)
        assert action.model == "claude-haiku-4-5-20251001"

    def test_max_tokens_error_returns_escalate_tokens(self):
        body = {"error": {"message": "max_tokens exceeded"}}
        action = handle_error(400, body)
        assert isinstance(action, EscalateTokens)
        assert action.max_tokens == 8192

    def test_prompt_too_long_returns_reactive_compact(self):
        body = {"error": {"message": "prompt is too long"}}
        action = handle_error(400, body)
        assert isinstance(action, ReactiveCompact)

    def test_prompt_too_long_alt_format(self):
        body = {"error": {"message": "prompt_too_long error"}}
        action = handle_error(400, body)
        assert isinstance(action, ReactiveCompact)

    def test_unknown_error_returns_no_recovery(self):
        action = handle_error(500, {"error": {"message": "internal error"}})
        assert isinstance(action, NoRecovery)

    def test_none_status_unknown_error(self):
        action = handle_error(None, {"error": {"message": "something"}})
        assert isinstance(action, NoRecovery)

    def test_none_body(self):
        action = handle_error(500, None)
        assert isinstance(action, NoRecovery)

    def test_error_body_string_not_dict(self):
        body = {"error": "plain string error"}
        action = handle_error(400, body)
        assert isinstance(action, NoRecovery)


class TestApplyRetry:
    @pytest.mark.asyncio
    async def test_apply_retry_sleeps(self):
        action = Retry(0.01)
        await apply_retry(action)
        # No assertion needed — just verify no exception
