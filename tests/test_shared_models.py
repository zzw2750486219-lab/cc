from __future__ import annotations

import pytest

from shared.models import AgentConfig, SandboxConfig, Task, TaskResult, TaskStatus


class TestTaskStatus:
    def test_enum_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_enum_is_string(self):
        assert isinstance(TaskStatus.PENDING, str)


class TestTask:
    def test_defaults(self):
        t = Task(prompt="hello")
        assert t.prompt == "hello"
        assert t.project_id == "default"
        assert len(t.id) == 12
        assert t.status == TaskStatus.PENDING
        assert t.model == "claude-sonnet-4-6-20251101"
        assert t.max_turns == 50
        assert t.tool_whitelist is None
        assert t.sandbox_id is None
        assert t.result_summary is None
        assert t.num_turns == 0
        assert t.cost_usd is None
        assert t.error is None
        assert t.webhook_url is None

    def test_full_init(self):
        t = Task(
            prompt="do it",
            project_id="proj-1",
            id="abc123",
            status=TaskStatus.RUNNING,
            model="claude-opus-4-7",
            max_turns=10,
            tool_whitelist=["bash", "file_read"],
            sandbox_id="sb-1",
            result_summary="done",
            num_turns=3,
            cost_usd=0.05,
            error="oops",
            webhook_url="https://hooks.example.com/cb",
        )
        assert t.prompt == "do it"
        assert t.project_id == "proj-1"
        assert t.id == "abc123"
        assert t.status == TaskStatus.RUNNING
        assert t.model == "claude-opus-4-7"
        assert t.max_turns == 10
        assert t.tool_whitelist == ["bash", "file_read"]
        assert t.sandbox_id == "sb-1"
        assert t.result_summary == "done"
        assert t.num_turns == 3
        assert t.cost_usd == 0.05
        assert t.error == "oops"
        assert t.webhook_url == "https://hooks.example.com/cb"

    def test_to_dict_includes_set_fields(self):
        t = Task(prompt="hello", project_id="p1")
        d = t.to_dict()
        assert d["prompt"] == "hello"
        assert d["project_id"] == "p1"
        assert d["status"] == "pending"
        # None fields excluded
        assert "cost_usd" not in d
        assert "error" not in d

    def test_to_dict_excludes_none_values(self):
        t = Task(prompt="x", cost_usd=None, error=None)
        d = t.to_dict()
        assert "cost_usd" not in d
        assert "error" not in d


class TestTaskResult:
    def test_defaults(self):
        r = TaskResult(task_id="t1", success=True)
        assert r.task_id == "t1"
        assert r.success is True
        assert r.summary == ""
        assert r.num_turns == 0
        assert r.cost_usd is None
        assert r.error is None

    def test_to_dict(self):
        r = TaskResult(task_id="t1", success=False, summary="failed", num_turns=5, cost_usd=1.0, error="boom")
        d = r.to_dict()
        assert d == {
            "task_id": "t1",
            "success": False,
            "summary": "failed",
            "num_turns": 5,
            "cost_usd": 1.0,
            "error": "boom",
        }


class TestAgentConfig:
    def test_defaults(self):
        c = AgentConfig(task_id="t1", prompt="hello")
        assert c.task_id == "t1"
        assert c.prompt == "hello"
        assert c.model == "claude-sonnet-4-6-20251101"
        assert c.max_turns == 50
        assert c.tool_whitelist is None
        assert c.llm_api_key == ""
        assert c.llm_base_url is None
        assert c.workspace_dir == "/workspace"

    def test_to_dict(self):
        c = AgentConfig(task_id="t1", prompt="hi", llm_api_key="sk-123", llm_base_url="https://api.example.com")
        d = c.to_dict()
        assert d["llm_api_key"] == "sk-123"
        assert d["llm_base_url"] == "https://api.example.com"


class TestSandboxConfig:
    def test_defaults(self):
        c = SandboxConfig()
        assert c.image == "cloud-agent-sandbox:latest"
        assert c.cpu == "1"
        assert c.memory == "512m"
        assert c.timeout == 600
        assert c.network is False
        assert c.env_vars == {}

    def test_custom(self):
        c = SandboxConfig(image="img:v2", cpu="2", memory="1g", timeout=300, network=True, env_vars={"A": "1"})
        assert c.image == "img:v2"
        assert c.env_vars == {"A": "1"}
        assert c.network is True
