# Cloud Agent Platform

> Self-hosted AI agent platform. Submit a task, get a sandboxed agent that thinks, codes, and ships — streamed in real time.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/tests-168%20passed-green" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
  <img src="https://img.shields.io/badge/lines-~2K%20Python-orange" alt="Code size">
</p>

---

## Quick Start

```bash
git clone https://github.com/zzw2750486219-lab/cc.git
cd cloud-agent-platform

# Inline mode — agent runs inside the API process
LLM_API_KEY="sk-..." make dev

# Docker sandbox mode — each task gets its own isolated container
LLM_API_KEY="sk-..." SANDBOX_MODE=docker make dev
```

Submit a task and watch it stream:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Scan this repo, find all TODOs and FIXMEs, write a report to TODOS.md", "max_turns": 10}'

# Stream live events
curl -N http://localhost:8000/api/v1/tasks/{task_id}/stream
```

That's it. No database. No message queue. No Kubernetes. Just Python and Docker.

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

**6 hook points** let you intercept every stage: `BEFORE_LLM_CALL`, `PRE_TOOL_USE`, `POST_TOOL_USE`, `BEFORE_STOP`, `ON_TASK_COMPLETE`, `ON_ERROR`. First non-None return short-circuits the chain — no need to modify the loop itself.

**4-stage compaction pipeline** keeps context under budget: budget tool results → snip old rounds → micro-summarize → full collapse. Applies the least destructive strategy that works.

---

## Two Execution Modes

| | Inline | Docker Sandbox |
|---|---|---|
| Agent runs in | Worker process | Isolated container |
| Isolation | None | `docker --cpus --memory --network` |
| Startup | Instant | ~0.5s |
| Workspace | `$WORKSPACE_DIR` or `/tmp/workspace` | `/workspace` in container |
| Use case | Dev, trusted workloads | Production, untrusted code execution |

Docker mode is what makes it a *Cloud* Agent Platform — each task gets a throwaway container. The worker writes `agent_config.json` to the container, runs `bootstrap.py`, parses the JSON output, and destroys the container. No network connection between orchestrator and sandbox.

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

SSE events: `task.created → task.started → task.tool_call → task.tool_result → task.completed`

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

---

## Testing

```bash
make test         # 168 tests in 2 seconds
```

Tests mirror the source tree. LLM calls are mocked, tools use `tmp_path`, Docker calls are patched, API uses `ASGITransport`. No API key, no network, no Docker daemon required.

---

## License

MIT
