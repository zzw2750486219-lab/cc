from __future__ import annotations

import os
import tempfile

import pytest

from tools.core.glob_search import handler as glob_search_handler


class TestGlobSearchTool:
    @pytest.mark.asyncio
    async def test_search_finds_files(self, temp_workspace):
        os.makedirs(os.path.join(temp_workspace, "src"))
        with open(os.path.join(temp_workspace, "src/a.py"), "w") as f:
            f.write("")
        with open(os.path.join(temp_workspace, "src/b.py"), "w") as f:
            f.write("")

        result = await glob_search_handler(
            {"pattern": "**/*.py"},
            {"workspace_dir": temp_workspace},
        )
        assert "src/a.py" in result
        assert "src/b.py" in result

    @pytest.mark.asyncio
    async def test_no_matches(self, temp_workspace):
        result = await glob_search_handler(
            {"pattern": "*.nonexistent"},
            {"workspace_dir": temp_workspace},
        )
        assert result == "(no matches)"

    @pytest.mark.asyncio
    async def test_search_in_subdirectory(self, temp_workspace):
        os.makedirs(os.path.join(temp_workspace, "sub"))
        with open(os.path.join(temp_workspace, "sub/x.txt"), "w") as f:
            f.write("")

        result = await glob_search_handler(
            {"pattern": "*.txt", "path": "sub"},
            {"workspace_dir": temp_workspace},
        )
        assert "sub/x.txt" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, temp_workspace):
        result = await glob_search_handler(
            {"pattern": "*", "path": "../../etc"},
            {"workspace_dir": temp_workspace},
        )
        assert "path traversal not allowed" in result

    @pytest.mark.asyncio
    async def test_default_workspace(self):
        result = await glob_search_handler(
            {"pattern": "*.nonexistent"},
            {},
        )
        assert result == "(no matches)"

    @pytest.mark.asyncio
    async def test_results_capped_at_200(self, temp_workspace):
        for i in range(250):
            with open(os.path.join(temp_workspace, f"file_{i:03d}.txt"), "w") as f:
                f.write("")

        result = await glob_search_handler(
            {"pattern": "*.txt"},
            {"workspace_dir": temp_workspace},
        )
        lines = result.split("\n")
        assert len(lines) <= 200
