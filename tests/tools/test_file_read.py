from __future__ import annotations

import os
import tempfile

import pytest

from tools.core.file_read import handler as file_read_handler


class TestFileReadTool:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, temp_workspace):
        file_path = os.path.join(temp_workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("hello world")

        result = await file_read_handler(
            {"file_path": "test.txt"},
            {"workspace_dir": temp_workspace},
        )
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_file_not_found(self, temp_workspace):
        result = await file_read_handler(
            {"file_path": "nonexistent.txt"},
            {"workspace_dir": temp_workspace},
        )
        assert "file not found" in result

    @pytest.mark.asyncio
    async def test_path_is_directory(self, temp_workspace):
        os.makedirs(os.path.join(temp_workspace, "mydir"))

        result = await file_read_handler(
            {"file_path": "mydir"},
            {"workspace_dir": temp_workspace},
        )
        assert "is a directory" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, temp_workspace):
        result = await file_read_handler(
            {"file_path": "../../etc/passwd"},
            {"workspace_dir": temp_workspace},
        )
        assert "path traversal not allowed" in result

    @pytest.mark.asyncio
    async def test_default_workspace(self):
        result = await file_read_handler(
            {"file_path": "nonexistent.txt"},
            {},
        )
        assert "file not found" in result

    @pytest.mark.asyncio
    async def test_workspace_root_itself(self, temp_workspace):
        result = await file_read_handler(
            {"file_path": "."},
            {"workspace_dir": temp_workspace},
        )
        assert "is a directory" in result
