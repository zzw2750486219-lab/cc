from __future__ import annotations

import asyncio
import os
from typing import Any

SCHEMA: dict[str, Any] = {
    "name": "bash",
    "description": "Execute a bash command inside the workspace directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60).",
            },
        },
        "required": ["command"],
    },
}


async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    command: str = args["command"]
    timeout: int = args.get("timeout", 60)
    workspace: str = context.get("workspace_dir", "/workspace")

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        return f"Error: command timed out after {timeout}s"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")

    parts: list[str] = []
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    if proc.returncode != 0:
        parts.append(f"[exit code: {proc.returncode}]")

    return "\n".join(parts) if parts else "(no output)"
