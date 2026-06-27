<div align="center">

[English](README.md) | [中文](README_CN.md)

</div>

# Cloud Agent Platform

> Self-hosted AI agent platform. Submit a natural-language task, get a sandboxed agent that thinks, codes, and ships — streamed in real time.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/tests-189%20passed-green" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
  <img src="https://img.shields.io/badge/code-~2K%20lines-orange" alt="Code size">
</p>

---

## Quick Start

```bash
git clone https://github.com/zzw2750486219-lab/cc.git
cd cc

# Install dependencies
pip install -e ".[dev]"

# Inline mode — agent runs inside the API process
LLM_API_KEY="sk-..." make dev

# Docker sandbox mode — each task gets its own isolated container
LLM_API_KEY="sk-..." SANDBOX_MODE=docker make dev
```

Submit a task and stream results:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Scan this repo, find all TODOs and FIXMEs, write a report to TODOS.md", "max_turns": 10}'

curl -N http://localhost:8000/api/v1/tasks/{task_id}/stream
```

That's it. No database, no message queue, no Kubernetes — just Python and Docker.

---

## How to Run

### Prerequisites

- Python 3.11+
- Docker (for sandbox mode only)
- LLM API key (Anthropic or DeepSeek-compatible)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | **Required.** Your LLM provider API key |
| `LLM_BASE_URL` | — | API base URL (set to `https://api.deepseek.com/anthropic` for DeepSeek) |
| `WORKER_CONCURRENCY` | `2` | Number of concurrent worker coroutines |
| `SANDBOX_MODE` | `inline` | `inline` or `docker` |
| `WORKSPACE_DIR` | `/tmp/workspace` | Agent workspace directory |
| `WORKER_ENABLED` | `1` | Set to `0` to disable worker (API only) |

### DeepSeek Example

```bash
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.deepseek.com/anthropic"
export LLM_MODEL="deepseek-v4-pro"
make dev
Then open `http://localhost:8000` — a dashboard with real-time event streaming, task history, workspace file viewer, and task cancel.

Swagger UI at `http://localhost:8000/docs`.

---

## What It Does

You give it a natural-language task. The platform:

1. Queues it on `asyncio.Queue`
2. A worker picks it up, builds an `AgentLoop`
3. The loop alternates: **LLM reasons → calls tools → LLM sees results → repeats**
4. Every tool call and result streams to you via **SSE**
5. When done (or max_turns exhausted), the task completes with a summary, turn count, and USD cost estimate

In Docker mode, step 3 runs inside an isolated container created on-demand and destroyed after completion.

---

## Architecture

```
POST /api/v1/tasks ──→ asyncio.Queue ──→ Worker Pool (N coroutines)
                                              │
         ┌────────────────────────────────────┤
         ▼                                    ▼
  Inline Mode                          Docker Sandbox Mode
  (AgentLoop in-process)               (bootstrap.py in container)
         │                                    │
         └────────────────┬───────────────────┘
                          ▼
                    AgentLoop.run()
                 while-turn cycle:
              LLM ←→ Tool Execution
                          │
                          ▼
                    TaskResult
```

## Layers

| Layer | Responsibility | Must NOT touch |
|-------|---------------|----------------|
| `agent_core/` | Agent loop, hooks, compaction, recovery, LLM client | `api/`, `orchestrator/`, `sandbox/` |
| `tools/` | bash, file_read, file_write, glob_search | same as above |
| `api/` | FastAPI app, SSE streaming, TaskStore | `agent_core/`, `tools/`, `sandbox/` |
| `orchestrator/` | TaskQueue, Worker pool, cron | same as above |
| `sandbox/` | SandboxProvider ABC, DockerProvider, bootstrap | everything else |
| `shared/` | Data types (single source of truth) | nothing — it's the contract |

---

## AgentLoop: The Core

```python
while turn < max_turns:
    BEFORE_LLM_CALL hook          # intercept/modify messages
    compaction                    # budget check → trim if needed
    LLM call + error recovery     # 429→retry, 529→fallback, token→escalate
    parse response                # text blocks + tool_use blocks
    if end_turn or no tools → break
    for each tool:
        PRE_TOOL_USE hook         # intercept args
        dispatch tool             # bash, file_read, file_write, glob_search
        POST_TOOL_USE hook        # intercept result
    turn++
return TaskResult
```

**6 hook points** let you intercept every stage: `BEFORE_LLM_CALL`, `PRE_TOOL_USE`, `POST_TOOL_USE`, `BEFORE_STOP`, `ON_TASK_COMPLETE`, `ON_ERROR`. First non-None return short-circuits the chain.

**4-stage compaction pipeline**: budget tool results → snip old rounds → micro-summarize → full collapse. Applies the least destructive strategy that works.

---

## Two Execution Modes

| | Inline | Docker Sandbox |
|---|---|---|
| Agent runs in | Worker process | Isolated container |
| Isolation | Per-task subdirectory | `docker --cpus --memory --network` |
| Startup | Instant | ~1s |
| Workspace | `$WORKSPACE_DIR/{task_id}` | `/workspace` in container |
| Use case | Dev, trusted workloads | Production, untrusted code execution |

Docker mode is what makes it a *Cloud* Agent Platform — each task gets a throwaway container. The worker writes `agent_config.json` to the container, runs `bootstrap.py`, parses the JSON output, and destroys the container. No network connection needed between orchestrator and sandbox.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/api/v1/tasks` | Submit a task |
| `GET` | `/api/v1/tasks` | List all tasks |
| `GET` | `/api/v1/tasks/{id}` | Get task status + result |
| `GET` | `/api/v1/tasks/{id}/stream` | SSE event stream |
| `POST` | `/api/v1/tasks/{id}/cancel` | Cancel a task |

SSE events (inline): `task.created → task.started → task.tool_call → task.tool_result → task.completed`

SSE events (docker): also includes `sandbox.created` (sandbox container up) and `sandbox.destroyed` (container destroyed)

---

## Tool System

Every tool follows a single signature:

```python
async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
```

Built-in tools: `bash`, `file_read`, `file_write`, `glob_search`. Add your own by creating `tools/core/my_tool.py` with `SCHEMA`, `handler`, and `register(registry)`.

---

## Design Decisions

- **`dataclass` over Pydantic** — zero-dependency shared types, explicit `to_dict()`
- **Lazy imports in worker** — API responds to health checks instantly, agent modules load on first task
- **`model_dump()` for LLM response blocks** — preserves non-standard blocks (e.g. `thinking`), enables DeepSeek & other non-Anthropic backends
- **`asyncio.Queue` over Redis/Kafka** — zero-config for single-node, clean interface for swapping to a distributed queue later
- **`AgentConfig` as bootstrap contract** — serialized to JSON, written into sandbox filesystem. No network handshake needed
- **`os.path.realpath` in tool path checks** — resolves symlinks before validating workspace containment, blocking symlink escape attacks
- **Hook callback exception isolation** — a crashing hook is logged and skipped, not fatal to the agent loop
- **Event-driven task list** — SSE events trigger sidebar refresh (30s fallback poll), browser title shows active count

---

## Testing

```bash
make test         # 189 tests in 2 seconds
```

Tests mirror the source tree. LLM calls are mocked, tools use `tmp_path`, Docker calls are patched, API uses `ASGITransport`. No API key, no network, no Docker daemon required.

---

## License

MIT
