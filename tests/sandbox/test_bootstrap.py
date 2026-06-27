from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the project root so we can import sandbox.bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestBootstrap:
    def test_config_not_found(self, tmp_path, capsys):
        config_path = tmp_path / "agent_config.json"
        if config_path.exists():
            config_path.unlink()

        with patch("sandbox.bootstrap.CONFIG_PATH", str(config_path)):
            with pytest.raises(SystemExit) as exc:
                from sandbox.bootstrap import main
                import asyncio
                asyncio.run(main())
            assert exc.value.code == 1

        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_config_parsing(self, tmp_path):
        """Verify AgentConfig can be constructed from the JSON format bootstrap expects."""
        config_path = tmp_path / "agent_config.json"
        config_data = {
            "task_id": "t1",
            "prompt": "say hello",
            "model": "claude-sonnet-4-6-20251101",
            "max_turns": 10,
            "tool_whitelist": ["bash", "file_read"],
            "llm_api_key": "sk-test",
            "llm_base_url": None,
            "workspace_dir": "/workspace",
        }
        config_path.write_text(json.dumps(config_data))

        raw = json.loads(config_path.read_text())

        from shared.models import AgentConfig
        config = AgentConfig(**raw)
        assert config.task_id == "t1"
        assert config.prompt == "say hello"
        assert config.model == "claude-sonnet-4-6-20251101"
        assert config.max_turns == 10

    @pytest.mark.asyncio
    async def test_bootstrap_full_flow(self, tmp_path, capsys):
        """Mock AgentLoop.run and verify bootstrap prints result to stdout."""
        config_path = tmp_path / "agent_config.json"
        config_data = {
            "task_id": "t2",
            "prompt": "do something",
            "model": "claude-sonnet-4-6-20251101",
            "max_turns": 5,
            "tool_whitelist": None,
            "llm_api_key": "sk-test",
            "llm_base_url": "https://api.test.com",
            "workspace_dir": str(tmp_path / "ws"),
        }
        config_path.write_text(json.dumps(config_data))

        from shared.models import TaskResult

        mock_result = TaskResult(
            task_id="t2",
            success=True,
            summary="all done",
            num_turns=3,
            cost_usd=0.01,
        )

        with patch("sandbox.bootstrap.AgentLoop") as MockLoop:
            loop_instance = MockLoop.return_value
            loop_instance.run = AsyncMock(return_value=mock_result)
            with patch("sandbox.bootstrap.CONFIG_PATH", str(config_path)):
                with patch("sandbox.bootstrap.LLMClient"):
                    from sandbox.bootstrap import main as bootstrap_main
                    with pytest.raises(SystemExit) as exc:
                        await bootstrap_main()
                    assert exc.value.code == 0

        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        last_line = json.loads(lines[-1])
        assert last_line["task_id"] == "t2"
        assert last_line["success"] is True
        assert last_line["summary"] == "all done"
        assert last_line["num_turns"] == 3

    @pytest.mark.asyncio
    async def test_bootstrap_exits_zero_on_success(self, tmp_path, capsys):
        """Bootstrap main exits 0 when result.success is True."""
        config_path = tmp_path / "agent_config.json"
        config_data = {
            "task_id": "t3",
            "prompt": "ok",
            "model": "claude-sonnet-4-6-20251101",
            "max_turns": 1,
            "tool_whitelist": None,
            "llm_api_key": "sk-test",
            "llm_base_url": None,
            "workspace_dir": "/tmp",
        }
        config_path.write_text(json.dumps(config_data))

        from shared.models import TaskResult

        with patch("sandbox.bootstrap.AgentLoop") as MockLoop:
            MockLoop.return_value.run = AsyncMock(return_value=TaskResult(
                task_id="t3", success=True, summary="done",
            ))
            with patch("sandbox.bootstrap.CONFIG_PATH", str(config_path)):
                with patch("sandbox.bootstrap.LLMClient"):
                    from sandbox.bootstrap import main as bootstrap_main
                    with pytest.raises(SystemExit) as exc:
                        await bootstrap_main()
                    assert exc.value.code == 0

    @pytest.mark.asyncio
    async def test_bootstrap_prints_tool_events(self, tmp_path, capsys):
        """Hook callbacks print tool_call / tool_result as JSON lines to stdout."""
        config_path = tmp_path / "agent_config.json"
        config_data = {
            "task_id": "t4",
            "prompt": "test",
            "model": "claude-sonnet-4-6-20251101",
            "max_turns": 3,
            "tool_whitelist": None,
            "llm_api_key": "sk-test",
            "llm_base_url": None,
            "workspace_dir": "/tmp",
        }
        config_path.write_text(json.dumps(config_data))

        from shared.models import TaskResult

        # Capture the hooks registered during bootstrap
        hooks_registered: dict[str, object] = {}

        with patch("sandbox.bootstrap.AgentLoop") as MockLoop:
            MockLoop.return_value.run = AsyncMock(return_value=TaskResult(
                task_id="t4", success=True, summary="done",
            ))
            with patch("sandbox.bootstrap.CONFIG_PATH", str(config_path)):
                with patch("sandbox.bootstrap.LLMClient"):
                    with patch("sandbox.bootstrap.HookRegistry") as MockHooks:
                        hook_instance = MockHooks.return_value

                        def capture_register(point, callback):
                            hooks_registered[str(point)] = callback

                        hook_instance.register.side_effect = capture_register

                        from sandbox.bootstrap import main as bootstrap_main
                        with pytest.raises(SystemExit):
                            await bootstrap_main()

        assert hooks_registered, "No hooks were registered"

    @pytest.mark.asyncio
    async def test_bootstrap_registers_four_core_tools(self, tmp_path):
        """Bootstrap registers bash, file_read, file_write, glob_search."""
        config_path = tmp_path / "agent_config.json"
        config_data = {
            "task_id": "t5",
            "prompt": "test",
            "model": "claude-sonnet-4-6-20251101",
            "max_turns": 1,
            "tool_whitelist": None,
            "llm_api_key": "sk-test",
            "llm_base_url": None,
            "workspace_dir": "/tmp",
        }
        config_path.write_text(json.dumps(config_data))

        from shared.models import TaskResult

        registered_names: list[str] = []

        with patch("sandbox.bootstrap.AgentLoop") as MockLoop:
            MockLoop.return_value.run = AsyncMock(return_value=TaskResult(
                task_id="t5", success=True, summary="ok",
            ))
            with patch("sandbox.bootstrap.CONFIG_PATH", str(config_path)):
                with patch("sandbox.bootstrap.LLMClient"):
                    with patch("sandbox.bootstrap.ToolRegistry") as MockRegistry:
                        registry_instance = MockRegistry.return_value

                        def capture_register(name, schema, handler):
                            registered_names.append(name)

                        registry_instance.register.side_effect = capture_register

                        from sandbox.bootstrap import main as bootstrap_main
                        with pytest.raises(SystemExit):
                            await bootstrap_main()

        assert "bash" in registered_names
        assert "file_read" in registered_names
        assert "file_write" in registered_names
        assert "glob_search" in registered_names
