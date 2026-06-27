# 我是怎么做这个题的

> 笔试题：从零搭一个 Cloud Agent Platform。趁刚做完，记录一下完整的想法和踩坑过程。

---

做完回头想，核心其实就一件事：**用户扔过来一段自然语言描述的任务，平台在隔离环境里跑一个 AI Agent，让它自己思考、自己动手、自己搞定，过程还必须能实时看见。**

拆开看就是五个问题：

1. 任务怎么收、怎么派？ — HTTP 收任务，放队列里排队
2. Agent 怎么跑？ — 一个 while 循环，来回倒腾：LLM 推理 → 调工具 → 看结果 → 继续推理
3. 隔离怎么做？ — Docker，一个任务一个容器，用完就扔
4. 怎么实时看进度？ — SSE 流式推事件
5. 以后怎么加东西？ — 接口定义清楚，Provider 模式，别写死

---

## 从哪里来的灵感

说实话这个设计很大程度上是抄的 Claude Code 的思路。Claude Code 跑起来就是一个循环：读你的需求 → 模型想想 → 调工具操作你的代码 → 把结果喂回去 → 继续想 → 直到搞完。这个模型太清晰了，直接映射成 `AgentLoop.run()`。

LLM 的 API 协议也是个关键。现在模型不只是吐文本了，返回的是结构化 block —— text block 和 tool_use block。那 Agent 循环要做的事就很简单：拿到响应，看看有没有 tool_use，有就去执行，把执行结果追加到对话里，再调用一轮。如此反复。

至于 Docker，它的容器模型跟任务处理天然就是一对：创建容器、跑任务、销毁容器，一气呵成。这种用完即弃的生命周期特别干净。

FastAPI 的 lifespan 机制也让事情简化了不少。Worker 不用单独起进程，可以直接挂在 API 进程里，共享一个 event loop。单机部署就变成了一件特别简单的事情。

---

## 为什么分了四层

一开始我想把所有代码塞一个目录里的，但越写越别扭：

- Agent 的核心逻辑（LLM 对话、工具分发、错误恢复）是纯算法，跟 HTTP 一毛钱关系都没有
- API 层（路由、SSE、请求解析）是 Web 框架的事，Agent 不应该知道它的存在
- 调度层（队列、Worker、定时任务）管的是怎么排任务、怎么分配，跟前两者都无关
- 沙箱层（Docker 操作、容器管理）甚至以后可能会换成 K8s 或者 Firecracker

所以四层不是刻意设计出来的，是写着写着自然分开的。Inner layer 不依赖 outer layer 的具体实现，这思路其实来自 Clean Architecture，但我没生搬硬套，只是在每层之间用类型定义做契约而已。

具体的边界规则很粗暴：

```
agent_core/ + tools/  → 不能碰 api/、orchestrator/、sandbox/
api/ + orchestrator/  → 不能碰 agent_core/、tools/、sandbox/
sandbox/              → 不能碰任何其他层
shared/               → 改了要所有人的同意，这是契约
```

这样一来改任何一层都不怕牵连其他层。

---

## while 循环 vs 状态机

真要"正规"一点应该用状态机。但我选了 while 循环，理由很简单：Agent 的执行过程本质就是一个顺序对话 —— 用户说一句、LLM 回一句、有工具就调用、结果加回去再问、重复。while 循环是这个心智模型的一对一映射。

状态机有的拦截能力，6 个 hook 点全给到了：进 LLM 前、调工具前、拿工具结果后、准备停的时候、任务完成后、出错了。首个返回非 None 的 hook 就短路整条链，这招是从 Web 中间件学来的。比如你想禁止某个工具调用，一个 hook 就搞定，循环代码完全不用动。

---

## 消息队列选型

这个判断挺重要。题目要求的是单节点系统，那引入 Redis 或 Kafka 就是在给部署加门槛 —— 用户还得先装一个消息队列才能跑起来。

`asyncio.Queue` 零配置零依赖，单节点够用。但我没有在业务代码里直接用裸的 `asyncio.Queue`，而是包了一层 `TaskQueue` 类，只暴露 `enqueue`、`dequeue`、`task_done` 三个方法。以后想换 Redis 或者 RabbitMQ，替换这一个类就够了。

`TaskStore` 同理，现在是内存字典，以后换 PostgreSQL 也只需要实现同样的接口，业务逻辑完全不用变。

---

## SandboxProvider 为什么用 ABC

Agent 不需要知道它跑在 Docker 还是 Kubernetes 还是 Firecracker 里。它只需要一个隔离环境。

所以用抽象基类定义接口：`create`、`execute`、`write_file`、`read_file`、`destroy`，五个方法。现在只有 `DockerProvider` 这一个实现，但接 `K8sProvider` 或者别的什么，五个方法写完就行，编排器代码一行不用动。这就是策略模式的经典应用场景。

---

## 几个值得一提的选择

### dataclass 而不是 Pydantic

Pydantic 确实很能打，但它是个外部依赖。内部类型定义不需要 Pydantic 的验证能力 —— 有类型标注、有 `to_dict()` 就完全够了。API 边界的校验归 FastAPI 管，不是 `shared/models.py` 该操心的事。

**不需要的东西，别引入。** 依赖多了反而累赘。

### Worker 懒加载

这个是个小优化但挺实用。Worker 模块在 API 启动时就被导入了，如果它一上来就 eager 加载 `agent_core`，那 `anthropic` SDK 的初始化会拖慢 API 启动。用懒加载的话，API 瞬间就能响应 health check，真正接到第一个任务时才去加载 Agent 模块。

放在 K8s 环境里这个很重要，readiness probe 慢了会被判不健康直接重启。

### model_dump() 保底

Anthropic SDK 返回的 block 是 Pydantic 模型。手动拼字典的话遇到非标准 block 就会丢字段。DeepSeek 的 `thinking` block 就是个典型例子 —— 我第一次测试时输出全空，debug 了半天才发现是 thinking block 的内容被默默扔掉了。`model_dump()` 一把梭，所有字段全保留。

### AgentConfig 走文件不走网络

Worker 和沙箱之间怎么传配置？两种办法：

- 网络通信：Worker 通过 HTTP 或 gRPC 把配置传给容器。问题是容器的网络策略可能会拦入站连接。
- 文件系统：Worker 把配置写成 JSON 放到共享目录里，Agent 启动时读出来。不需要任何网络连接。

我选了文件系统。`AgentConfig` 序列化 JSON，写到 `/home/user/agent_config.json`，`bootstrap.py` 一读就完事。简单可靠不纠结。

### 渐进式 Context Compaction

LLM 的 context window 是有限资源，对话太长就得裁。但裁多了信息丢得多，裁少了又不够。

所以我搞了个四段渐进的管线：

```
阶段 1: 单个工具输出截断到 4KB（最轻的裁剪）
阶段 2: 只保留最近 10 轮工具对话（丢掉最旧的）
阶段 3: 微型压缩，保留最近 4 条消息 + AI 生成的摘要
阶段 4: 整段对话压成一条摘要（最激进的策略）
```

每执行完一个阶段就检查一下预算够不够，够了就停。这样总是用**最轻的策略满足需求**。这个想法是从垃圾回收的分代策略那来的 —— 能轻就别重。

### 错误恢复分级

LLM API 报错不能一刀切，不同错得不同治：

| 错误 | 啥意思 | 怎么治 | 逻辑 |
|------|--------|--------|------|
| 429 | 请求太多被限了 | 指数退避等一下再重试 | 临时状态 |
| 529 | 模型那边过载了 | 切到更轻量的模型 | 降级保命 |
| max_tokens | 输出空间给少了 | 扩到 8K tokens | 多给点空间就行 |
| prompt_too_long | 上下文太长了 | 先压缩再说 | 先把包袱卸了 |

每种错误对应一个 `RecoveryAction`，`handle_error` 看完状态码和错误信息就返回对应的动作。这个也是从 HTTP 中间件的重试逻辑里抄的思路。

---

## 实际踩的坑

**第一个坑：DeepSeek 的 thinking block。** Anthropic SDK 调 DeepSeek 的时候，返回里会出现 `type: "thinking"` 的 block。一开始我用手动判断 `block.type == "text"` 的方式解析，结果 thinking 的内容全丢了，最后输出啥也没有。改 `block.model_dump()` 保留所有字段才搞定。

**第二个坑：Docker 沙箱出不了网。** 最开始我给容器设了 `--network=none`，想着这样最安全。结果 Agent 特么连 LLM API 都访问不了，直接废了。改成正常网络就行了 —— 安全隔离不一定要断网，容器本身已经是隔离边界了。

**第三个坑：/workspace 不存在。** 预设挂载 `/workspace` 目录，但宿主机上压根没有这个路径。改成先检测，不存在就 fallback 到 `/tmp/workspace`。

**第四个坑：Compaction 搞出连续 user 消息。** 压缩之后可能冒出两条连续的 `role: "user"` 的消息，Anthropic API 要求必须是 user/assistant 交替出现，直接报错。加了个角色交替检查才解决。

**第五个坑：inline 模式文件路径不安全。** symlink 如果指向工作目录外面，能读到宿主机的任意文件。一开始用的 `os.path.normpath` 没管 symlink，换成 `os.path.realpath` 先解析再比较才算彻底堵住。

**第六个坑：前端 SSE 不出事件。** JavaScript 里 `const task` 写在 try 块里面，外面的 `EventSource` 拿不到这个变量，ReferenceError 静默挂了。声明提到 try 外面就正常了。这个 bug 折磨了我好一阵。

---

## 总结

这系统复杂的不是代码量（核心就两千行不到），复杂的是设计取舍 —— 怎么切模块、怎么定接口、怎么保证能扩展、各种边界情况怎么处理。

我自己觉得做得好的几个点：
- 四层分得还算干净，每层能单独测，互不影响
- Hook 系统的拦截能力够灵活，循环本身保持简单
- Provider 模式让沙箱后端随时能换
- 189 个测试把关键路径都罩住了，测试目录跟源码结构一一对应
- 零外部依赖，部署就 Python + Docker

后面想继续做的话：
- 多 Agent 协作，一个大任务自动拆成多个子任务并行跑
- 更多的工具，比如浏览器、API 调用、数据库查询
- 权限粒度控制，工具白名单和参数校验
- 持久化存储任务结果和历史对话
