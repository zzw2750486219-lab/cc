from __future__ import annotations

import glob
import os
from typing import Any

SCHEMA: dict[str, Any] = {
    "name": "glob_search",
    "description": "Search for files matching a glob pattern. Returns relative file paths.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g. '**/*.py' or '*.txt').",
            },
            "path": {
                "type": "string",
                "description": "Subdirectory within workspace to search (default: workspace root).",
            },
        },
        "required": ["pattern"],
    },
}


def register(registry) -> None:
    registry.register("glob_search", SCHEMA, handler)


async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    pattern: str = args["pattern"]
    subdir: str = args.get("path", "")
    workspace: str = context.get("workspace_dir", "/workspace")

    search_dir = os.path.normpath(os.path.join(workspace, subdir))
    if not search_dir.startswith(os.path.normpath(workspace) + os.sep) and search_dir != os.path.normpath(workspace):
        return "Error: path traversal not allowed"

    full_pattern = os.path.join(search_dir, pattern)
    try:
        matches = sorted(glob.glob(full_pattern, recursive=True))
    except Exception as exc:
        return f"Error: {exc}"

    if not matches:
        return "(no matches)"

    relative = [os.path.relpath(m, workspace) for m in matches]
    return "\n".join(relative[:200])
