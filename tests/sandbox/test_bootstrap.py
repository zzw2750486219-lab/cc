from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
