from __future__ import annotations

import os
from typing import Any

SCHEMA: dict[str, Any] = {
    "name": "file_read",
    "description": "Read the contents of a file. Path is relative to the workspace.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read, relative to workspace root.",
            },
        },
        "required": ["file_path"],
    },
}


def register(registry) -> None:
    registry.register("file_read", SCHEMA, handler)


async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    file_path: str = args["file_path"]
    workspace: str = context.get("workspace_dir", "/workspace")

    full_path = os.path.normpath(os.path.join(workspace, file_path))
    workspace_real = os.path.realpath(workspace)
    try:
        full_real = os.path.realpath(full_path)
    except OSError:
        parent_real = os.path.realpath(os.path.dirname(full_path))
        full_real = os.path.normpath(os.path.join(parent_real, os.path.basename(full_path)))
    if not full_real.startswith(workspace_real + os.sep) and full_real != workspace_real:
        return "Error: path traversal not allowed"

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except IsADirectoryError:
        return f"Error: path is a directory: {file_path}"
    except PermissionError:
        return f"Error: permission denied: {file_path}"
    except Exception as exc:
        return f"Error: {exc}"
