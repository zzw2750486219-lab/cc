# 解题思路与设计思考

> 这是一道笔试题：构建一个 Cloud Agent Platform。以下是我从零到一的完整思考过程。

## 一、题目分析

题目核心需求：用户提交自然语言任务 → 平台在隔离环境中启动 Agent → Agent 调用 LLM 推理、执行工具 → 循环直到完成 → 实时返回结果。

拆解下来，需要解决五个问题：

1. **怎么接收任务并调度？** — HTTP API + 任务队列
2. **Agent 怎么运行？** — while-turn 循环：LLM 推理 ↔ 工具执行
3. **怎么隔离执行？** — Docker 容器，一个任务一个容器
4. **怎么实时反馈？** — SSE（Server-Sent Events）流式推送
5. **怎么扩展？** — 清晰的接口和分层，Provider 模式

## 二、启发来源

设计这个系统时，我受了几个东西的影响：

**Claude Code 的 Agent Loop。** Claude Code 本质上就是一个 while 循环：读用户输入 → LLM 推理 → 调用工具 → 把结果塞回对话 → 再推理 → 直到完成。这个模型非常清晰，直接映射到 `AgentLoop.run()`。

**OpenAI 的 Function Calling 协议。** LLM 不再只输出文本，而是输出结构化的 `tool_use` block。这意味着 Agent 循环只需要做一件事：解析响应里的 tool_use，执行工具，把结果塞回去。

**Docker 的隔离模型。** 每个容器就是一个即用即抛的沙箱——创建、执行、销毁。这种生命周期和任务处理天然匹配。

**FastAPI 的 lifespan 机制。** Worker 不需要独立进程，可以嵌入 API 进程的 lifespan，共享同一个 asyncio event loop。这让单节点部署变得极其简单。

## 三、架构设计思路

### 为什么用四层分离？

一开始我考虑过把所有代码放在一起，但很快就发现不行：

- Agent 核心逻辑（LLM 调用、工具分发、错误恢复）是纯算法，跟 HTTP 无关
- API 层（路由、SSE、请求解析）是 Web 框架的事，跟 Agent 无关
- 调度层（队列、Worker、定时任务）是编排逻辑，跟上述两者都无关
- 沙箱层（Docker 操作、容器管理）甚至可能被替换成 K8s 或 Firecracker

**所以天然就是四层。** 每层有自己的职责，通过 `shared/models.py` 里的类型定义作为契约连接。这其实是从 Clean Architecture 借鉴的思路——内层不依赖外层的具体实现。

具体规则：
- `shared/` 是单一数据源，禁止随意修改
- `agent_core/` + `tools/` 不碰 `api/`、`orchestrator/`、`sandbox/`
- `api/` + `orchestrator/` 不碰 `agent_core/`、`tools/`
- `sandbox/` 不碰任何其他层

这样改任何一层都不会影响其他层。

### 为什么用 while 循环而不是状态机？

状态机更"正规"，但 Agent 执行本质就是顺序对话：

```
用户消息 → LLM 响应 → 工具调用 → 工具结果 → LLM 再响应 → ...
```

while 循环直接映射这个心智模型。而且通过 6 个 hook 拦截点（`BEFORE_LLM_CALL`、`PRE_TOOL_USE`、`POST_TOOL_USE`、`BEFORE_STOP`、`ON_TASK_COMPLETE`、`ON_ERROR`），可以做到和状态机一样的拦截能力，但不需要状态机的仪式感。

Hook 的"首个非 None 返回值短路"机制是我从 Web 中间件学来的——一个 hook 返回了结果，后面的就不用跑了。这让安全策略（比如禁止某些工具调用）可以用一个 hook 干净地实现，完全不用改循环逻辑。

### 为什么用 asyncio.Queue 而不是 Redis/Kafka？

这个问题很关键。我判断的出发点是：**题目要求的是单节点系统**。

如果引入 Redis 或 Kafka，部署门槛直接上升——用户需要先装一个消息队列才能跑起来。`asyncio.Queue` 零配置、零依赖，对于单节点场景完全够用。

但我没有把 `asyncio.Queue` 硬编码进代码。`TaskQueue` 是一个明确的封装类，只暴露 `enqueue`、`dequeue`、`task_done` 三个方法。未来要换成 Redis 或 RabbitMQ，替换这一个类就行，接口不变。

同样的思路用在 `TaskStore` 上——现在是内存字典，换成 PostgreSQL 也只需要实现同样的接口。

### 为什么 SandboxProvider 用 ABC（抽象基类）？

Agent 不需要知道它跑在 Docker 还是 K8s 还是 Firecracker 里。它只需要一个隔离的执行环境。

所以 `SandboxProvider` 是一个 ABC，定义了 `create`、`execute`、`write_file`、`read_file`、`destroy` 五个方法。现在只有 `DockerProvider` 一个实现，但未来加 `K8sProvider` 或 `FirecrackerProvider` 只需要实现这五个方法，编排器代码一行不用改。

这种 Provider 模式其实就是策略模式（Strategy Pattern），面向对象里最经典的扩展方式。

## 四、关键设计决策的思考

### 1. `dataclass` 而不是 Pydantic

Pydantic 功能很强，但它是外部依赖。对于内部类型定义来说，dataclass 完全够用——有类型注解、有 `to_dict()`、实例化快。而且 `shared/models.py` 里的类型不属于 API 层，不需要 Pydantic 的验证能力。API 边界的验证由 FastAPI 通过请求体解析完成。

**一句话：不需要的东西，不要引入。**

### 2. Worker 懒加载

Worker 模块在 API 启动时就被导入了。如果它 eager 加载 `agent_core`，那 `anthropic` SDK 的加载会拖慢 API 启动。用了懒加载后，API 可以瞬间响应 health check，`agent_core` 只在真正处理第一个任务时才加载。

这是一个小优化，但在容器编排环境中（K8s 的 readiness probe）很重要——服务慢了会被认为不健康。

### 3. `model_dump()` 处理 LLM 响应

Anthropic SDK 的响应 block 是 Pydantic 模型。如果手动重建字典（`{"type": block.type, "text": block.text}`），遇到非标准 block（比如 DeepSeek 的 `thinking` block）就会丢字段。`model_dump()` 一次性保留所有字段。

这个坑是我实际踩出来的——用 DeepSeek 测试时发现输出为空，追到根因是 thinking block 的内容被丢弃了。

### 4. `AgentConfig` 作为沙箱契约

Worker 和沙箱之间怎么传配置？两种选择：

- **网络通信**：Worker 通过 HTTP 或 gRPC 把配置传给容器内的 Agent。问题是容器的网络策略可能限制入站连接。
- **文件系统**：Worker 把配置写入容器文件系统，Agent 启动时读取。这是最可靠的方式——不需要任何网络连接。

我选了文件系统方案。`AgentConfig` 序列化为 JSON，写入 `/home/user/agent_config.json`，`bootstrap.py` 读取这个文件构建 AgentLoop。**简单、可靠、零网络依赖。**

### 5. Context Compaction 的渐进式策略

LLM 的 context window 是有限的。如果对话太长，必须裁剪。但裁剪得越激进，信息丢失越多。

所以设计了四个阶段的渐进式策略：

```
阶段 1: 工具结果截断（单个输出截断到 4KB）
阶段 2: 保留最近 10 个工具回合（丢最旧的）
阶段 3: 微型压缩（保留最近 4 条消息 + AI 生成摘要）
阶段 4: 全量折叠（整段对话压缩成一条摘要消息）
```

每个阶段执行后检查预算——够了就停。这意味着我们永远施加**必要程度最低的破坏性策略**。这个思路受启发于垃圾回收的分代策略——不是一次性全量回收，而是从轻到重逐级尝试。

### 6. 错误恢复的分级处理

LLM API 的错误不能一把抓。不同错误需要不同策略：

| 错误 | 含义 | 策略 | 理由 |
|------|------|------|------|
| 429 | 限流 | 指数退避重试 | 瞬时错误，稍后即可 |
| 529 | 过载 | 切到轻量模型 | 用更便宜的模型扛 |
| max_tokens | 输出空间不足 | 扩容到 8K tokens | 给模型更多空间 |
| prompt_too_long | 输入太长 | 压缩后重试 | 缩小上下文再试 |

每种错误有对应的 `RecoveryAction`，`handle_error` 根据状态码和错误消息返回对应动作。这个设计受启发于 HTTP 重试中间件的分级处理逻辑。

## 五、踩过的坑

**坑 1：DeepSeek 的 thinking block。** 用 Anthropic SDK 调 DeepSeek 时，响应里会出现 `type: "thinking"` 的 block。手动解析 `block.type == "text"` 的方式直接丢掉了这些 block，导致最终输出为空。改成了 `block.model_dump()` 保留所有字段。

**坑 2：Docker 沙箱连不上 LLM API。** 最初容器设置了 `--network=none`，容器内 Agent 根本无法出站访问 LLM API。改成 `network=True` 解决。安全隔离不一定要断网——容器本身就是隔离边界。

**坑 3：/workspace 目录不存在。** 容器内预设 `/workspace` 但宿主机上不一定有这个目录。改成了自动检测，宿主机不存在就 fallback 到 `/tmp/workspace`。

**坑 4：Compaction 导致连续 user 消息。** 压缩后可能出现两个连续 `role: "user"` 的消息，违反 Anthropic API 的 alternating role 要求。加了一个角色交替检查。

## 六、总结

这个系统的核心复杂度不在代码量（核心代码不到 2000 行），而在设计——怎么分拆模块、怎么定义接口、怎么保证扩展性、怎么处理边界情况。

我认为做得比较好的几点：
- 四层分离，接口清晰，每层可独立测试
- Hook 系统提供了灵活的拦截能力，同时保持循环逻辑干净
- Provider 模式让沙箱后端可替换
- 168 个测试覆盖所有关键路径，测试目录和源码一一对应
- 零外部依赖（Redis、数据库等），部署只需 Python + Docker

如果继续做，我会考虑：
- 多 Agent 协作（一个任务拆成多个子任务并行执行）
- 工具生态（浏览器、API 调用、数据库查询）
- 更细粒度的权限控制（工具白名单 + 参数校验）
- 持久化存储（任务结果、Agent 对话历史）
