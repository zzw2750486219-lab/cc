from __future__ import annotations

import asyncio
import random
from typing import Any

MAX_RETRIES_429 = 5
BASE_DELAY_429 = 2.0
MAX_DELAY_429 = 60.0
FALLBACK_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS_DEFAULT = 4096
MAX_TOKENS_ESCALATED = 8192


class RecoveryAction:
    pass


class Retry(RecoveryAction):
    def __init__(self, delay: float) -> None:
        self.delay = delay


class FallbackModel(RecoveryAction):
    def __init__(self, model: str) -> None:
        self.model = model


class EscalateTokens(RecoveryAction):
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens


class ReactiveCompact(RecoveryAction):
    pass


class NoRecovery(RecoveryAction):
    pass


def handle_error(
    status_code: int | None,
    error_body: dict[str, Any] | None,
    attempt: int = 0,
) -> RecoveryAction:
    if status_code == 429:
        if attempt >= MAX_RETRIES_429:
            return NoRecovery()
        delay = min(BASE_DELAY_429 * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY_429)
        return Retry(delay)

    if status_code == 529:
        return FallbackModel(FALLBACK_MODEL)

    error_msg = _error_text(error_body).lower()

    if "max_tokens" in error_msg or "token" in error_msg and "exceed" in error_msg:
        return EscalateTokens(MAX_TOKENS_ESCALATED)

    if "prompt" in error_msg and ("too_long" in error_msg or "too long" in error_msg):
        return ReactiveCompact()

    return NoRecovery()


def _error_text(body: dict[str, Any] | None) -> str:
    if body is None:
        return ""
    err = body.get("error", {})
    if isinstance(err, dict):
        return err.get("message", str(err))
    return str(err)


async def apply_retry(action: Retry) -> None:
    await asyncio.sleep(action.delay)
