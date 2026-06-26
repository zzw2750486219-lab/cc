---
name: agent-core
description: White-box agent loop — while-True cycle, tool dispatch, hooks, compaction, error recovery, and core tools.
---

# Agent Core

Implement the agent loop and tool system in these directories:

- `agent_core/` — AgentLoop, HookRegistry, CompactionPipeline, ToolRegistry, LLM client
- `tools/core/` — bash, file_read, file_write, glob_search

## Package layout

```
agent_core/
├── __init__.py
├── loop.py
├── hooks.py
├── compaction.py
├── recovery.py
├── tools/
│   ├── __init__.py
│   └── registry.py
└── llm/
    ├── __init__.py
    └── client.py

tools/core/
├── __init__.py
├── bash.py
├── file_read.py
├── file_write.py
└── glob_search.py
```

## Architecture rules

1. AgentLoop.run() while turn < max_turns: BeforeLLMCall → compaction → LLM → tool dispatch → PostToolUse → loop
2. HookRegistry: BeforeLLMCall, PreToolUse, PostToolUse, BeforeStop, OnTaskComplete, OnError. First non-None blocks.
3. CompactionPipeline: tool_result_budget → snip_compact → micro_compact → full_compact
4. ToolRegistry is table-driven: register(name, schema, handler) → dispatch(name, args)
5. Error recovery: 429 backoff, 529 fallback, max_tokens escalate, prompt_too_long reactive compact
6. Import from shared.models: AgentConfig, TaskResult, TaskStatus

## Global rules

Follow all rules in `CLAUDE.md` at the repo root — imports, signatures, error handling, boundaries. This SKILL defines your specific scope on top of those rules.

## Do NOT touch

api/, orchestrator/, sandbox/, pyproject.toml, docker-compose.yml, Dockerfile, Makefile
