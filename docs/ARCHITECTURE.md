# Cloud Agent Platform — 架构

用户提交自然语言 task → 平台在隔离 sandbox 中启动自主 agent → LLM 推理 + 调用 tools → while-turn 循环直到完成 → SSE 实时流式返回。

~2000 行 Python，单机运行，每层可独立测试。168 tests。

## 架构

```
     POST /tasks  ─→  TaskQueue  ─→  Worker Pool  ─→  AgentLoop  ─→  result
        │            (asyncio)       (N coroutines)    (while-turn)
   GET /stream ←───────────────── SSE events ──────────────────────┘
```

Worker 内嵌在 FastAPI lifespan 中启动，与 API 共享同一个 `TaskStore` 和 `TaskQueue`，无需外部 broker。

## 分层

```
shared/models.py       # 单一数据源，所有类型定义
agent_core/            # Agent 引擎：loop, hooks, compaction, recovery, llm client
tools/core/            # bash, file_read, file_write, glob_search
api/                   # FastAPI + SSE + TaskStore
orchestrator/          # TaskQueue, Worker, cron
sandbox/               # SandboxProvider ABC, DockerProvider, bootstrap
```

每层只读写自己的目录。`shared/` 是契约，不可擅自修改。

## 数据模型 (`shared/models.py`)

```
Task:  prompt, model, max_turns, tool_whitelist, sandbox_id, status
TaskResult:  success, summary, num_turns, cost_usd, error
AgentConfig:  task_id, llm_api_key, llm_base_url, workspace_dir  ← bootstrap 契约
SandboxConfig:  image, cpu, memory, timeout, network
```

状态机: `PENDING → RUNNING → COMPLETED | FAILED`, 可被 cancel 打断。

## AgentLoop 核心算法

```python
while turn < max_turns:
    BEFORE_LLM_CALL hook      # 可拦截/修改 messages
    compaction check           # 超预算则逐级压缩
    LLM call + error recovery  # 429→retry, 529→fallback, token→escalate
    parse response             # text_blocks + tool_blocks (via model_dump)
    if end_turn or no tools → break
    for each tool:
        PRE_TOOL_USE hook → dispatch → POST_TOOL_USE hook
    append tool_results, turn++
return TaskResult
```

采用 while 循环而非状态机，因为 agent 执行本质就是顺序对话，while 直接映射这个模型。

## Hooks: 6 个拦截点

```
BEFORE_LLM_CALL   →  修改 messages              PRE_TOOL_USE   →  修改 tool args
POST_TOOL_USE     →  修改 tool result           BEFORE_STOP    →  拦截 stop
ON_TASK_COMPLETE  →  覆盖 final result          ON_ERROR       →  观察 error
```

`async def hook(**kwargs) -> Any | None`，首个非 None 返回值短路整条 hook 链。

## Error Recovery

| 错误 | 策略 |
|------|------|
| 429 (rate limit) | Exponential backoff, max 5 retries |
| 529 (overload) | Fallback to `claude-haiku-4-5` |
| max_tokens exceeded | Escalate 4096 → 8192 |
| prompt_too_long | Reactive compaction then retry |
| Other | `TaskResult(success=False)` |

## Compaction Pipeline

渐进式：tool result budget (截断到 4KB) → snip (保留最近 10 个 tool round) → micro (4 条消息 + summary) → full (全对话折叠为 summary)

每阶段执行后检查预算，到阈值即停——只施加必要程度最低的破坏性策略。

## Tool 系统

统一签名：`async def handler(args: dict[str, Any], context: dict[str, Any]) -> str`

每个 tool module 暴露: `SCHEMA`、`handler`、`register(registry)`。

file_read / file_write 内置 path traversal 防护，拒绝工作区外的访问。

## 两种执行模式

| | Inline | Docker sandbox |
|------|------|-------------|
| Agent 位置 | Worker 进程内 | 独立容器 |
| 隔离性 | 无 | `docker --cpus --memory --network` |
| 适用 | 开发、可信任务 | 生产、不可信代码 |

Docker 模式下每个 task 获得独立即抛容器：create → write `agent_config.json` → execute `bootstrap.py` → parse stdout → destroy。

## API

| 端点 | 用途 |
|------|------|
| `POST /api/v1/tasks` | 提交 task，入队 |
| `GET /api/v1/tasks/{id}` | 查询状态和结果 |
| `GET /api/v1/tasks/{id}/stream` | SSE 事件流 |
| `POST /api/v1/tasks/{id}/cancel` | 取消 pending/running task |

SSE 事件: `task.created → started → tool_call → tool_result → completed`

## 关键设计决策

1. **`shared/models.py` 用 dataclass 而非 Pydantic** — 零依赖，`to_dict()` 显式无魔法。
2. **Worker 懒加载 agent_core** — API 启动时立即响应 health check，任务执行时才 import。
3. **`model_dump()` 解析 LLM response blocks** — 保留 thinking 等非标准 block，兼容 DeepSeek 等非 Anthropic 模型。
4. **单进程架构** — `asyncio.Queue` + 共享 `TaskStore`，零外部依赖。多节点时替换 queue/store 实现即可。
5. **AgentConfig 作 bootstrap 契约** — 序列化写入容器 `/home/user/agent_config.json`，sandbox 不需要网络连接。

## 运行

```bash
LLM_API_KEY="sk-..." make dev                 # inline 模式
LLM_API_KEY="sk-..." SANDBOX_MODE=docker make dev  # sandbox 模式
```

## 扩展点

新 tool → `tools/core/my_tool.py` 实现 SCHEMA + handler + register
新 sandbox backend → 实现 `SandboxProvider` ABC (K8s, Firecracker, etc.)
多节点 → 换 PostgreSQL TaskStore + Redis TaskQueue
认证 → 在 middleware 链添加 `X-API-Key` 验证
