"""Shared type contracts — all agents agree on these."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    prompt: str
    project_id: str = "default"
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    status: TaskStatus = TaskStatus.PENDING
    model: str = "claude-sonnet-4-6-20251101"
    max_turns: int = 50
    tool_whitelist: list[str] | None = None
    sandbox_id: str | None = None
    result_summary: str | None = None
    num_turns: int = 0
    cost_usd: float | None = None
    error: str | None = None
    webhook_url: str | None = None
    workspace_files: list[str] | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "prompt": self.prompt, "project_id": self.project_id,
            "status": self.status.value, "model": self.model,
            "max_turns": self.max_turns, "tool_whitelist": self.tool_whitelist,
            "sandbox_id": self.sandbox_id, "result_summary": self.result_summary,
            "num_turns": self.num_turns, "cost_usd": self.cost_usd,
            "error": self.error, "webhook_url": self.webhook_url,
            "workspace_files": self.workspace_files,
        }
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class TaskResult:
    task_id: str
    success: bool
    summary: str = ""
    num_turns: int = 0
    cost_usd: float | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "success": self.success,
            "summary": self.summary, "num_turns": self.num_turns,
            "cost_usd": self.cost_usd, "error": self.error,
        }


@dataclass
class AgentConfig:
    task_id: str
    prompt: str
    model: str = "claude-sonnet-4-6-20251101"
    max_turns: int = 50
    tool_whitelist: list[str] | None = None
    llm_api_key: str = ""
    llm_base_url: str | None = None
    workspace_dir: str = "/workspace"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "prompt": self.prompt,
            "model": self.model, "max_turns": self.max_turns,
            "tool_whitelist": self.tool_whitelist,
            "llm_api_key": self.llm_api_key,
            "llm_base_url": self.llm_base_url,
            "workspace_dir": self.workspace_dir,
        }


@dataclass
class SandboxConfig:
    image: str = "cloud-agent-sandbox:latest"
    cpu: str = "1"
    memory: str = "512m"
    timeout: int = 600
    network: bool = False
    env_vars: dict[str, str] = field(default_factory=dict)

