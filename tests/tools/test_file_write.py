from __future__ import annotations

import os
import tempfile

import pytest

from tools.core.file_write import handler as file_write_handler


class TestFileWriteTool:
    @pytest.mark.asyncio
    async def test_write_file(self, temp_workspace):
        result = await file_write_handler(
            {"file_path": "output.txt", "content": "hello world"},
            {"workspace_dir": temp_workspace},
        )
        assert "Wrote 11 bytes" in result
        assert "output.txt" in result

        with open(os.path.join(temp_workspace, "output.txt")) as f:
            assert f.read() == "hello world"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, temp_workspace):
        result = await file_write_handler(
            {"file_path": "deep/nested/file.txt", "content": "data"},
            {"workspace_dir": temp_workspace},
        )
        assert "Wrote 4 bytes" in result
        assert os.path.exists(os.path.join(temp_workspace, "deep/nested/file.txt"))

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, temp_workspace):
        result = await file_write_handler(
            {"file_path": "../../etc/hacked", "content": "evil"},
            {"workspace_dir": temp_workspace},
        )
        assert "path traversal not allowed" in result

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, temp_workspace):
        file_path = os.path.join(temp_workspace, "existing.txt")
        with open(file_path, "w") as f:
            f.write("old")

        result = await file_write_handler(
            {"file_path": "existing.txt", "content": "new"},
            {"workspace_dir": temp_workspace},
        )
        assert "Wrote 3 bytes" in result
        with open(file_path) as f:
            assert f.read() == "new"
