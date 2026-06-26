from __future__ import annotations

import os
import tempfile

import pytest

from tools.core.bash import handler as bash_handler


class TestBashTool:
    @pytest.mark.asyncio
    async def test_successful_command(self, temp_workspace):
        result = await bash_handler(
            {"command": "echo hello"},
            {"workspace_dir": temp_workspace},
        )
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_command_with_exit_code(self, temp_workspace):
        result = await bash_handler(
            {"command": "exit 1"},
            {"workspace_dir": temp_workspace},
        )
        assert "[exit code: 1]" in result

    @pytest.mark.asyncio
    async def test_stderr_output(self, temp_workspace):
        result = await bash_handler(
            {"command": "echo err >&2"},
            {"workspace_dir": temp_workspace},
        )
        assert "[stderr]" in result

    @pytest.mark.asyncio
    async def test_no_output(self, temp_workspace):
        result = await bash_handler(
            {"command": "true"},
            {"workspace_dir": temp_workspace},
        )
        assert result == "(no output)"

    @pytest.mark.asyncio
    async def test_timeout(self, temp_workspace):
        result = await bash_handler(
            {"command": "sleep 5", "timeout": 1},
            {"workspace_dir": temp_workspace},
        )
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_default_workspace(self, temp_workspace):
        result = await bash_handler(
            {"command": "pwd"},
            {"workspace_dir": temp_workspace},
        )
        assert temp_workspace in result

    @pytest.mark.asyncio
    async def test_workspace_isolation(self, temp_workspace):
        """Command runs in specified workspace directory."""
        result = await bash_handler(
            {"command": "pwd"},
            {"workspace_dir": temp_workspace},
        )
        assert temp_workspace in result
