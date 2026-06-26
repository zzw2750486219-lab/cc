# Cloud Agent Platform — Global Rules

All agents and developers working in this repo must follow these rules.

## Project layout (DO NOT REORGANIZE)

```
cloud-agent-platform/
├── shared/models.py       # THE SINGLE SOURCE OF TRUTH for data types
├── agent_core/            # Agent loop, hooks, compaction, recovery, tool registry, LLM client
│   ├── llm/client.py
│   └── tools/registry.py
├── tools/core/            # Tool implementations (bash, file_read, file_write, glob_search)
├── api/                   # FastAPI application
├── orchestrator/          # Worker, task queue, cron
├── sandbox/               # SandboxProvider ABC, DockerProvider, bootstrap.py
│   └── providers/
└── tests/                 # Mirrors source structure
```

## Import rules

- Always: `from shared.models import AgentConfig, TaskResult, TaskStatus, Task, SandboxConfig`
- Always: `from agent_core.xxx import ...` (full dotted path, never relative)
- Always: `from tools.core.xxx import ...` for tool modules
- `shared/` is NOT a package to modify — it's the contract. Never change it without global agreement.
- Every package directory MUST have an `__init__.py` (can be empty).

## Tool handler signature

Every tool handler follows this exact signature:

```python
async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    # args = tool input from LLM
    # context = {"workspace_dir": "/workspace"}
    # Return string result (stdout, error message, etc.)
```

Every tool module exposes: `SCHEMA` (dict), `handler` (async function), `register(registry)` (function).

## Hook system

- 6 hook points: `before_llm_call`, `pre_tool_use`, `post_tool_use`, `before_stop`, `on_task_complete`, `on_error`
- Hook callbacks are async: `async def my_hook(**kwargs) -> Any | None`
- First non-None return value BLOCKS the pipeline (stops further hooks, may override result)
- HookRegistry.run() is async, takes `HookPoint` enum + kwargs

## Error recovery

- 429 → exponential backoff retry (2^attempt + jitter, max 60s, max 5 retries)
- 529 → switch to fallback model (`claude-haiku-4-5-20251001`)
- max_tokens error → escalate from 4096 to 8192
- prompt_too_long → reactive compact then retry
- Non-recoverable → return `TaskResult(success=False, error=str(exc))`

## Bootstrap contract (sandbox entry point)

`sandbox/bootstrap.py` runs inside the sandbox container:
1. Read `/home/user/agent_config.json` → `AgentConfig`
2. Init `LLMClient(config)`, `ToolRegistry()`, `HookRegistry()`, `CompactionPipeline()`
3. Register 4 core tools: bash, file_read, file_write, glob_search
4. `AgentLoop(...).run()`
5. Print `json.dumps(result.to_dict())` to stdout
6. `sys.exit(0 if result.success else 1)`

## Testing

- Test directory mirrors source: `tests/agent_core/test_loop.py`, `tests/tools/test_bash.py`, etc.
- Use `pytest` with `pytest-asyncio` for async tests
- `tests/conftest.py` adds project root to `sys.path`
- Tool tests use `tmp_path` fixture — never touch real filesystem

## What each layer owns

| Layer | Owns | Must NOT touch |
|-------|------|----------------|
| agent_core + tools | `agent_core/`, `tools/` | `api/`, `orchestrator/`, `sandbox/`, `pyproject.toml` |
| platform | `api/`, `orchestrator/`, `pyproject.toml`, `Makefile`, `Dockerfile`, `docker-compose.yml` | `agent_core/`, `tools/`, `sandbox/` |
| sandbox | `sandbox/` | `api/`, `orchestrator/`, `agent_core/`, `tools/` |

## General rules

- No deleting or renaming files created by another agent layer. Edit only your own.
- No introducing new dependencies without adding them to `pyproject.toml`.
- No generating placeholder/stub code — every implementation must be real and complete.
- Use `from __future__ import annotations` at the top of every Python file.
- Type hints on all public function signatures.
- No `*args`, no `**kwargs` except in hook callbacks.
- Every return path in a function must return the same type.
- Don't catch `Exception` broadly unless it's at a system boundary (API handler, agent loop top-level).
