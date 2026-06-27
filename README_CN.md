<div align="center">

[English](README.md) | [中文](README_CN.md)

</div>

# Cloud Agent Platform

> 自托管的 AI Agent 平台。提交自然语言任务，平台在隔离沙箱中启动自主 Agent，实时流式返回结果。

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/tests-168%20passed-green" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
  <img src="https://img.shields.io/badge/code-~2K%20lines-orange" alt="Code size">
</p>

---

## 快速开始

```bash
git clone https://github.com/zzw2750486219-lab/cc.git
cd cc

# 安装依赖
pip install -e ".[dev]"

# Inline 模式 — Agent 在 API 进程内运行
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

---

## 运行配置

### 环境要求

- Python 3.11+
- Docker（仅 sandbox 模式需要）
- LLM API key（Anthropic 或 DeepSeek 兼容）

### 环境变量

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `LLM_API_KEY` | — | **必填。** LLM API 密钥 |
| `LLM_BASE_URL` | — | API 地址（DeepSeek 填 `https://api.deepseek.com/anthropic`）|
| `WORKER_CONCURRENCY` | `2` | 并发 Worker 协程数 |
| `SANDBOX_MODE` | `inline` | `inline` 或 `docker` |
| `WORKSPACE_DIR` | `/tmp/workspace` | Agent 工作目录 |
| `WORKER_ENABLED` | `1` | 设为 `0` 仅启动 API，不启动 Worker |

### DeepSeek 示例

```bash
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.deepseek.com/anthropic"
export LLM_MODEL="deepseek-v4-pro"
make dev
```

浏览器打开 `http://localhost:8000/docs` 查看 Swagger 文档。

---

## 核心原理

用户提交自然语言任务后：

1. 任务入队 `asyncio.Queue`
2. Worker 取任务，构建 `AgentLoop`
3. 循环执行：**LLM 推理 → 调用工具 → LLM 获取结果 → 继续**，直至完成
4. 每次工具调用和结果通过 **SSE** 实时推送
5. 任务完成后返回摘要、轮次数和成本估算

Docker 模式下第 3 步运行在即时创建、用完即毁的隔离容器中。

---

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

---

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

---

## 两种执行模式

| | Inline | Docker Sandbox |
|---|---|---|
| Agent 运行位置 | Worker 进程内 | 独立容器 |
| 隔离性 | 无 | `docker --cpus --memory --network` |
| 启动耗时 | 即时 | ~0.5s |
| 工作目录 | `$WORKSPACE_DIR` 或 `/tmp/workspace` | 容器内 `/workspace` |
| 适用场景 | 开发、可信任务 | 生产、不可信代码执行 |

Docker 模式是 "Cloud" 的含义所在——每个任务获得独立即抛容器：Worker 写入 `agent_config.json`，执行 `bootstrap.py`，解析 stdout JSON，销毁容器。

---

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

---

## 工具系统

所有工具遵循统一签名：

```python
async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
```

内置工具：`bash`、`file_read`、`file_write`、`glob_search`。扩展只需在 `tools/core/` 下新建模块，实现 `SCHEMA`、`handler`、`register(registry)`。

---

## 设计决策

- **`dataclass` 而非 Pydantic** — 零依赖，`to_dict()` 无魔法序列化
- **Worker 懒加载** — API 即时响应 health check，agent 模块在首任务时才加载
- **`model_dump()` 解析响应** — 保留 `thinking` 等非标准 block，兼容 DeepSeek 等模型
- **`asyncio.Queue` 而非 Redis/Kafka** — 单节点零配置，接口清晰，多节点时替换即可
- **`AgentConfig` 作 Bootstrap 契约** — 序列化为 JSON 写入沙箱文件系统，无需网络握手

---

## 测试

```bash
make test         # 168 个测试，2 秒完成
```

测试目录与源码一一对应。LLM 调用 mock、工具使用 `tmp_path`、Docker 调用 patch、API 使用 `ASGITransport`。无需 API key、网络或 Docker daemon。

---

## 项目结构

```
cloud-agent-platform/
├── shared/models.py           # 单一数据源——所有类型定义
├── agent_core/                # Agent 引擎：loop, hooks, compaction, recovery, LLM client
├── tools/core/                # 工具实现：bash, file_read, file_write, glob_search
├── api/                       # FastAPI + SSE + TaskStore
├── orchestrator/              # TaskQueue, Worker, cron
├── sandbox/                   # SandboxProvider ABC, DockerProvider, bootstrap
├── tests/                     # 测试目录，与源码一一对应
└── docs/                      # 架构文档
```

## License

MIT
