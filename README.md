# Cloud Agent Platform

> Self-hosted AI agent platform. Submit a task, get a sandboxed agent that thinks, codes, and ships — streamed in real time.
>
> 自托管的 AI Agent 平台。提交自然语言任务，平台在隔离沙箱中启动自主 Agent，实时流式返回结果。

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
cd cc

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

---

<br>

# 中文说明

## 快速开始

```bash
git clone https://github.com/zzw2750486219-lab/cc.git
cd cc

# Inline 模式 — agent 在 API 进程内运行
LLM_API_KEY="sk-..." make dev

# Docker 沙箱模式 — 每个任务一个独立隔离容器
LLM_API_KEY="sk-..." SANDBOX_MODE=docker make dev
```

提交任务并实时查看流式输出：

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Scan this repo, find all TODOs and FIXMEs, write a report to TODOS.md", "max_turns": 10}'

curl -N http://localhost:8000/api/v1/tasks/{task_id}/stream
```

无需数据库、消息队列、Kubernetes，仅需 Python 和 Docker。

## 核心原理

用户提交自然语言任务后：

1. 任务入队 `asyncio.Queue`
2. Worker 取任务，构建 `AgentLoop`
3. 循环执行：**LLM 推理 → 调用工具 → LLM 获取结果 → 继续**，直至完成
4. 每次工具调用和结果通过 **SSE** 实时推送
5. 任务完成后返回摘要、轮次数和成本估算

Docker 模式下第 3 步运行在即时创建、用完即毁的隔离容器中。

## 架构

```
POST /api/v1/tasks ──→ asyncio.Queue ──→ Worker 池（N 协程）
                                              │
         ┌────────────────────────────────────┤
         ▼                                    ▼
  Inline 模式                           Docker Sandbox 模式
  (进程内 AgentLoop)                     (容器内 bootstrap.py)
         │                                    │
         └────────────────┬───────────────────┘
                          ▼
                    AgentLoop.run()
                 while-turn 循环:
              LLM ←→ 工具执行
                          │
                          ▼
                    TaskResult
```

## 分层

| 层 | 职责 | 禁止触碰 |
|-------|---------------|----------------|
| `agent_core/` | Agent 循环、hook、compaction、recovery、LLM 客户端 | `api/`、`orchestrator/`、`sandbox/` |
| `tools/` | bash、file_read、file_write、glob_search | 同上 |
| `api/` | FastAPI 应用、SSE 流、TaskStore | `agent_core/`、`tools/`、`sandbox/` |
| `orchestrator/` | 任务队列、Worker 池、定时任务 | 同上 |
| `sandbox/` | SandboxProvider 抽象类、DockerProvider、bootstrap | 所有其他目录 |
| `shared/` | 数据类型定义（单一数据源）| 无 — 它是契约 |

## AgentLoop 核心算法

```python
while turn < max_turns:
    BEFORE_LLM_CALL hook          # 拦截/修改消息
    compaction                    # 预算检查 → 超出则裁剪
    LLM 调用 + 错误恢复           # 429→重试, 529→降级, token→扩容
    解析响应                       # text blocks + tool_use blocks
    if end_turn or 无工具调用 → break
    每个工具:
        PRE_TOOL_USE hook         # 拦截参数
        分发执行                    # bash, file_read, file_write, glob_search
        POST_TOOL_USE hook        # 拦截结果
    turn++
return TaskResult
```

**6 个 hook 拦截点**：`BEFORE_LLM_CALL`、`PRE_TOOL_USE`、`POST_TOOL_USE`、`BEFORE_STOP`、`ON_TASK_COMPLETE`、`ON_ERROR`。首个非 None 返回值短路整条 hook 链，无需修改循环本身。

**4 阶段 compaction 管线**：按激进程度递进——tool result 截断 → 保留最近轮次 → 微型摘要 → 全量折叠。每阶段后检查预算，仅施加必要程度最低的策略。

## 两种执行模式

| | Inline | Docker Sandbox |
|---|---|---|
| Agent 运行位置 | Worker 进程内 | 独立容器 |
| 隔离性 | 无 | `docker --cpus --memory --network` |
| 启动耗时 | 即时 | ~0.5s |
| 工作目录 | `$WORKSPACE_DIR` 或 `/tmp/workspace` | 容器内 `/workspace` |
| 适用场景 | 开发、可信任务 | 生产、不可信代码执行 |

Docker 模式是 "Cloud" 的含义所在——每个任务获得独立即抛容器：Worker 写入 `agent_config.json`，执行 `bootstrap.py`，解析 stdout JSON，销毁容器。

## API

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/health` | 存活检查 |
| `POST` | `/api/v1/tasks` | 提交任务 |
| `GET` | `/api/v1/tasks` | 列出所有任务 |
| `GET` | `/api/v1/tasks/{id}` | 获取任务状态与结果 |
| `GET` | `/api/v1/tasks/{id}/stream` | SSE 事件流 |
| `POST` | `/api/v1/tasks/{id}/cancel` | 取消任务 |

SSE 事件：`task.created → task.started → task.tool_call → task.tool_result → task.completed`

## 工具系统

所有工具遵循统一签名：

```python
async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
```

内置工具：`bash`、`file_read`、`file_write`、`glob_search`。扩展只需在 `tools/core/` 下新建模块，实现 `SCHEMA`、`handler`、`register(registry)`。

## 设计决策

- **`dataclass` 而非 Pydantic** — 零依赖，`to_dict()` 无魔法序列化
- **Worker 懒加载** — API 即时响应 health check，agent 模块在首任务时才加载
- **`model_dump()` 解析响应** — 保留 `thinking` 等非标准 block，兼容 DeepSeek 等模型
- **`asyncio.Queue` 而非 Redis/Kafka** — 单节点零配置，接口清晰，多节点时替换即可
- **`AgentConfig` 作 Bootstrap 契约** — 序列化为 JSON 写入沙箱文件系统，无需网络握手

## 测试

```bash
make test         # 168 个测试，2 秒完成
```

测试目录与源码一一对应。LLM 调用 mock、工具使用 `tmp_path`、Docker 调用 patch、API 使用 `ASGITransport`。无需 API key、网络或 Docker daemon。

## License

MIT
