#!/usr/bin/env python3
"""Agent bootstrap — runs inside the sandbox container.

1. Read /home/user/agent_config.json → AgentConfig
2. Init LLMClient, ToolRegistry, HookRegistry, CompactionPipeline
3. Register core tools (bash, file_read, file_write, glob_search)
4. AgentLoop.run(), print JSON result to stdout
5. Exit 0 on success, 1 on failure
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from shared.models import AgentConfig

from agent_core.loop import AgentLoop
from agent_core.hooks import HookRegistry
from agent_core.compaction import CompactionPipeline
from agent_core.tools.registry import ToolRegistry
from agent_core.llm.client import LLMClient

from tools.core.bash import register as register_bash
from tools.core.file_read import register as register_file_read
from tools.core.file_write import register as register_file_write
from tools.core.glob_search import register as register_glob_search

CONFIG_PATH = "/home/user/agent_config.json"


async def main() -> None:
    config_path = Path(CONFIG_PATH)
    if not config_path.exists():
        print(json.dumps({"error": f"{CONFIG_PATH} not found"}), file=sys.stderr)
        sys.exit(1)

    raw = json.loads(config_path.read_text())
    config = AgentConfig(**raw)

    llm_client = LLMClient(config)
    tool_registry = ToolRegistry()
    hook_registry = HookRegistry()
    compaction = CompactionPipeline()

    register_bash(tool_registry)
    register_file_read(tool_registry)
    register_file_write(tool_registry)
    register_glob_search(tool_registry)

    loop = AgentLoop(
        config=config,
        llm_client=llm_client,
        tool_registry=tool_registry,
        hook_registry=hook_registry,
        compaction_pipeline=compaction,
    )

    result = await loop.run()

    print(json.dumps(result.to_dict()))

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
