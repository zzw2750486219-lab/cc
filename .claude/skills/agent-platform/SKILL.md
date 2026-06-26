---
name: agent-platform
description: API server (FastAPI + SSE), task queue, orchestrator worker pool, project config.
---

# Agent Platform

Implement the API layer, orchestration, and project config.

- `api/` — FastAPI, SSE streaming, middleware
- `orchestrator/` — Worker pool, task queue, cron
- Root: pyproject.toml, docker-compose.yml, Dockerfile, Makefile

## Package layout

```
api/
├── __init__.py
├── main.py
├── routes/
│   ├── __init__.py
│   └── tasks.py
└── middleware.py

orchestrator/
├── __init__.py
├── worker.py
├── queue.py
└── cron.py
```

## API

POST /api/v1/tasks, GET /api/v1/tasks, GET /api/v1/tasks/{id}, GET /api/v1/tasks/{id}/stream, POST /api/v1/tasks/{id}/cancel

SSE events: task.started, task.turn, task.tool_call, task.tool_result, task.completed, task.failed

## Architecture rules

1. In-memory task store (dict[str, Task]) for Phase 1
2. SSE streaming, keep-alive every 15s
3. OrchestratorWorker: dequeue → sandbox → agent → stream → cleanup
4. Import from shared.models: Task, TaskResult, TaskStatus, AgentConfig, SandboxConfig

## Global rules

Follow all rules in `CLAUDE.md` at the repo root — imports, signatures, error handling, boundaries. This SKILL defines your specific scope on top of those rules.

## Do NOT touch

agent_core/, tools/, sandbox/
