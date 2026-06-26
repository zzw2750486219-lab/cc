from __future__ import annotations

import os
from typing import Any

SCHEMA: dict[str, Any] = {
    "name": "file_write",
    "description": "Write content to a file. Creates parent directories if needed. Path is relative to the workspace.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write, relative to workspace root.",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    },
}


async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    file_path: str = args["file_path"]
    content: str = args["content"]
    workspace: str = context.get("workspace_dir", "/workspace")

    full_path = os.path.normpath(os.path.join(workspace, file_path))
    if not full_path.startswith(os.path.normpath(workspace) + os.sep) and full_path != os.path.normpath(workspace):
        return "Error: path traversal not allowed"

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} bytes to {file_path}"
    except Exception as exc:
        return f"Error: {exc}"
