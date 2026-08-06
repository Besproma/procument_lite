# 采购智能助手轻量版开发文档

> 文档状态：Core / Business 物理分层已完成，本文与当前代码保持一致
>
> 代码状态：后端前三层（接入与应用、编排核心、资源访问）已完成物理分层，前端已迁移到 Vue 3
>
> 本文是本项目唯一权威的开发依据。聊天记录、旧项目代码和其他目录文档均不得替代本文。

## 0. 文档目的

本文必须达到以下目标：

1. 后续开发 Agent 无需读取旧项目，即可理解并完整实现本项目。
2. 业务规则、技术边界、接口协议、目录结构和验收条件没有依赖猜测的空白。
3. 使用 LangGraph、LangChain、AG-UI 和成熟前端组件，避免重新实现通用 Agent 基础设施。
4. 代码必须具有高可读性和可扩展性；中文注释必须充分、准确且详细，但不建设当前业务用不到的复杂平台能力。
5. 明确区分本地 Mock 验收与真实生产接入验收。

除非用户后续明确修改本文，开发 Agent 不得自行扩大或缩小范围。

## 1. 当前物理分层重构基线（最高优先级）

本节是本次重构的最高优先级约束。全文只能出现下面这一套有效生产目录；旧路径已经删除，
文档中的代码引用也必须指向新路径。

### 1.1 本次要解决的问题

当前代码把通用运行引擎和采购业务放在同一个 Python 包层级中。例如，Core 的装配文件
直接 import 智能分流、知识推荐和 IOI Delegate。这样新增一个业务场景时，开发者必须修改
引擎代码，业务规则也容易逐渐进入引擎。

本次重构必须达到以下结果：

1. 后端生产代码物理分成 `core` 和 `business` 两个 Python 包。
2. 依赖方向只有 `business → core`；Core 不得 import Business。
3. 新增一个使用既有交互原语的业务场景，只修改 Business 目录。
4. Core 仍可因真正的平台能力升级而演进，但普通业务变更不得修改 Core。
5. 代码保持一个服务、一个仓库和一个进程，不拆微服务，不使用运行时扫描。
6. 前端使用 Vue 3 重写展示层，但不修改现有 API、SSE、数据库表和业务规则。

### 1.2 用一句话理解两层

```text
Core 负责“流程引擎怎样可靠运行”
Business 负责“采购业务要做什么”
```

判断一段代码放哪一层时，不看旧目录名字，只看它是否理解采购业务含义：

| 代码知道的内容 | 所属层 | 例子 |
|---|---|---|
| 超时、重试、Checkpoint、SSE、Trace、HTTP 连接池 | `core` | `GraphRunner`、`ExecutionContext` |
| 商品、栏目、IOI、预算、合同、采购规则 | `business` | `SmartRoutingState`、IOI Delegate |
| 通用表单、选项、按钮的生命周期 | `core` | `FormWaitRequest`、Action 消费 |
| “栏目选择”字段必须是候选集合中的一个 | `business` | 栏目输入校验器 |
| 结构化模型调用和备用模型切换 | `core` | Model Runtime |
| “从用户话术提取商品名称” | `business` | 采购字段模型任务 |

### 1.3 目标目录（后端）

前端在本轮保持现状。后端目标目录如下；每个目录只承担表中写明的职责。

```text
backend/src/procurement_assistant/
├── main.py                          # 稳定启动入口，只调用 Business 装配入口
├── core/                             # 通用运行引擎；绝不 import business
│   ├── api/                          # HTTP、SSE、身份、错误和会话快照接入
│   ├── config/                       # CoreSettings 和模型连接配置对象
│   ├── delegates/                    # 通用模型、HTTP、数据库和流式调用适配
│   │   ├── common/                   # 调用上下文、HTTP 客户端和内部流事件
│   │   ├── database/                 # Run、场景、Action、Checkpoint、记忆和 Trace 数据访问
│   │   └── model/                    # OpenAI 兼容模型运行时和结构化输出接口
│   ├── domain/                       # ID、生命周期和通用系统错误
│   ├── memory/                       # 后台任务管理和长期记忆更新接口
│   ├── observability/                # Span、Trace 收集、Checkpoint 计时和落库
│   ├── orchestration/                # Run 应用服务、GraphRunner、运行上下文和通用路由
│   │   └── router/                   # 顶层 ReAct 路由与场景切换协调
│   ├── protocol/                     # AG-UI 信封、通用输入、交互和事件传输
│   └── shared/                       # 可测试时钟和 ID 生成器
│
└── business/                         # 采购业务；可以 import core
    ├── administration/               # 发布前结束旧场景的业务管理命令
    ├── bootstrap.py                  # 唯一业务装配入口，创建所有具体实现
    ├── config/                       # AppSettings 和 BusinessSettings
    ├── delegates/                    # IOI、栏目、搜索、知识和排队的具体 Delegate
    │   ├── agents/                   # 外围采购 Agent 适配
    │   └── services/                 # 搜索、知识缓存和排队服务适配
    ├── domain/                       # 商品、栏目、预算、记忆等采购领域模型
    ├── interaction/                  # 业务表单字段、操作编号和等待点工厂
    ├── memory/                       # 个人采购记忆的生成和合并实现
    ├── prompts/                      # 一个模型任务一个 Prompt 文件
    ├── protocol/                     # 商品、排队、采购跳转和快照策略等业务协议
    ├── registry/                     # 场景、Atomic Tool、模型任务和交互的静态注册
    ├── scenarios/                    # 按场景纵向聚合 State、Node、Route、Graph
    │   ├── knowledge/                # 知识推荐场景及 definition.py
    │   ├── smart_routing/            # 智能分流场景及 definition.py
    │   └── subgraphs/                # 只能被业务 Graph 调用的内部子图
    └── tools/                        # 一个 Scenario/Atomic Tool 一个文件和一个类
```

`main.py` 位于两层之外，是稳定的进程入口。它可以 import `business.bootstrap`；这不会
违反 Core 边界，因为它不是 Core。Core 的任何文件都不能反向 import `business`。

### 1.4 依赖和装配方向

```text
main.py
  ↓
business.bootstrap
  ├─ 读取 CoreSettings + BusinessSettings
  ├─ 创建 Core 基础设施
  ├─ 创建 Business Delegate、Model Task 和交互 Registry
  ├─ 创建每个场景的 ScenarioDefinition
  └─ 把 Business Catalog 交给 core.build_runtime(...)
        ↓
      Core API / Application / GraphRunner / Protocol / Trace
```

允许：

```text
business → core
main     → business
test_support → business/core
tests    → business/core
```

禁止：

```text
core → business
生产代码 → tests
生产代码 → test_support
```

本轮暂不增加自动 import 检查；依赖规则先写入本文和代码评审清单，后续再增加静态门禁。

### 1.5 Core 的稳定通用能力

Core 不能知道“IOI 是什么”，但要稳定提供以下机制：

- 统一 API 接入、身份读取、请求校验和 SSE 返回；
- Run 幂等、同一 `threadId` 租约、场景启动/恢复/结束；
- LangGraph `ainvoke`、`interrupt`、Checkpoint 和 24 小时恢复；
- 顶层 ReAct 场景路由。它只能看到 Business 注入的 Scenario Tool 描述；
- 统一 Delegate 调用：单次超时、Run 总截止时间、有限重试、Trace 和流式接收；
- 统一数据库生命周期、短事务、Action 消费和通用记忆存取；
- 通用文字、表单、选项、按钮、重试和事件信封；
- 配置校验、容量限制、错误边界和资源关闭。

Core 的 Delegate 调用不是字符串路由器。Business 把一个已经绑定了具体 Delegate 的
异步函数交给 `context.call_delegate(operation=...)`，Core 只在函数外层添加超时、重试、
Trace 和流式保护。`name` 仅用于 Trace 标签，不能触发动态 import。

### 1.6 Business 的可变内容

Business 必须拥有以下内容：

- 每个场景的 State、Node、Route、Graph 和 Scenario Tool；
- 采购外围 Agent 的强类型接口、请求/响应模型和 HTTP 映射；
- Atomic Tool 的实现和描述；
- 业务模型任务、输入/输出模型和 Prompt；
- 采购表单、栏目候选校验、采购 Action 和业务事件 payload；
- 场景专属数据库 Repository 和迁移；
- 业务缓存 Key、TTL、序列化模型和缓存未命中策略；
- 个人记忆中采购字段的含义和记忆更新规则。

### 1.7 场景注册协议

Core 定义不含业务含义的注册协议，Business 创建已经装配好的对象：

```python
@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """Core 只使用这些通用字段，不读取任何采购 State 字段。"""

    scenario_id: str
    display_name: str
    description: str
    tool: ScenarioTool
    graph: CompiledGraph
```

Business 的 `registry/scenarios.py` 显式汇总所有 `definition.py` 生成的定义并触发 Core
启动校验。Registry 保存对象和函数，不保存模块路径、类名字符串或数据库配置。

新增场景的最短路径：

1. 新增 `business/scenarios/<scene>/`，至少包含 `definition.py`、`state.py`、`nodes.py`、
   `routes.py`、`graph.py`；每个 Scenario Tool 仍使用独立文件和独立类。
2. 在 `business/registry/scenarios.py` 显式增加一个定义。
3. 在 `business/bootstrap.py` 为该场景创建强类型依赖并编译 Graph。
4. 如果使用新表单、模型任务、Atomic Tool 或业务事件，在对应 Registry 增加一项。
5. 如果只使用已有通用交互原语，Core 和前端都不改。

### 1.8 通用协议和业务协议

Core 的 `ScenarioTriggerInput.scenario_id` 是受长度约束的普通字符串，不写死场景枚举。
Business `ScenarioRegistry` 在启动时建立允许列表，应用层在启动/按钮请求时校验它；未注册编号不得
启动 Graph。

Core 负责 AG-UI 事件信封、事件编号、顺序、去重、SSE 和持久化。Business 负责商品列表、
排队信息、采购跳转等业务 payload。现有对外 JSON 字段和值必须保持不变，因此前端本轮不改。

Core 的表单和 Action 只保存通用结构。Business Registry 提供具体输入模型和校验器，例如
“栏目 option_id 必须在上一次调用返回的候选集合中”。Core 负责 Action 所属用户、场景、
过期和一次性消费，不能理解栏目规则。

### 1.9 模型、Prompt、Delegate、缓存和配置归属

| 能力 | Core | Business |
|---|---|---|
| 模型 | 结构化调用、超时、备用模型、异常治理 | 任务 ID、输入/输出模型、Prompt 和任务封装 |
| Delegate | 通用调用上下文、HTTP 客户端、流式 sink | IOI/栏目/搜索/知识等具体接口和适配器 |
| 数据库 | 连接池、事务边界、Checkpoint、Run、记忆和 Trace | 场景专属 Repository、表和迁移 |
| 缓存 | 通用 Cache 接口、连接和故障处理 | Key、TTL、值模型和缓存语义 |
| 配置 | `CoreSettings` 和基础设施校验 | `BusinessSettings` 和业务配置校验 |
| 记忆 | 按 user_id 存取、异步调度和并发治理 | 采购记忆字段、提取 Prompt 和非关键使用方式 |

### 1.10 迁移清单

重构时按下表迁移，不能只新增空目录后继续使用旧路径：

| 重构前路径 | 重构后归属 | 处理方式 |
|---|---|---|
| `api/` | `core/api/` | 保留通用 HTTP/SSE 行为，不 import 具体场景 |
| `business/bootstrap.py` | `business/bootstrap.py` | 成为唯一知道所有采购实现的装配入口 |
| `config.py` | `core/config/` + `business/config/` | 基础设施配置与采购配置分开 |
| `delegates/common/` | `core/delegates/common/` | 超时上下文、HTTP 和通用流事件 |
| `delegates/database/` | `core/delegates/database/` | 通用助手数据、Checkpoint 和 Trace |
| `delegates/model/` | `core/delegates/model/` | 只保留与业务任务 ID 无关的模型运行时 |
| `delegates/agents/`、`delegates/services/` | `business/delegates/` | IOI、栏目、搜索、知识和排队 |
| `domain/errors.py`、`identifiers.py`、`lifecycle.py` | `core/domain/` | 通用错误、ID 和生命周期 |
| `domain/procurement.py` | `business/domain/` | 商品、栏目、预算和采购结果模型 |
| `memory/task_manager.py` | `core/memory/` | 通用后台任务生命周期 |
| `memory/updater.py` | Core 接口 + `business/memory/` 实现 | Core 调度，Business 定义记忆补丁含义 |
| `observability/` | `core/observability/` | 全链路 Trace 通用能力 |
| `orchestration/application.py`、`graph_runner.py`、`runtime.py` | `core/orchestration/` | 通用 Run/Graph 生命周期 |
| `orchestration/router/` | `core/orchestration/router/` | 只读取 Business 注入的场景目录 |
| `orchestration/scenarios/`、`subgraphs/` | `business/scenarios/` | 场景纵向聚合 |
| `orchestration/tools/`、`catalog/` | Core 合同 + Business 实现/Registry | 删除 Core 对具体 Tool 的 import |
| `orchestration/action_inputs.py`、`wait_factory.py` | Core 原语 + Business 定义 | 通用生命周期与业务字段校验拆开 |
| `prompts/` | `business/prompts/` | 一个业务模型任务一个 Prompt |
| `core/protocol/` | `core/protocol/` + `business/protocol/` | 通用信封与业务 payload 拆开 |
| `shared/` | `core/shared/` | 时钟和 ID；业务复用代码另放 Business Shared |
| `administration/` | `business/administration/` | 依赖 Core 数据库，但读取 Business 生产配置 |

### 1.11 重构验收和执行顺序

本次执行顺序固定为：

```text
1. 先更新本文的目标目录、协议和验收规则
2. 不等待额外审核，直接按本文移动和重构后端代码
3. 保持现有接口、SSE、数据库和业务行为不变
4. 运行编译、静态检查、契约测试和集成测试
5. 生成连续的新手代码阅读指南
6. 删除被新指南替代的旧走查文档并更新 README
```

重构期间不引入业务版本号，不为旧路径保留转发模块。按既有决策，部署新代码时结束
无法由新 Graph 安全恢复的旧场景，不做旧/新 Graph 兼容恢复。

## 2. 术语说明

本文尽量使用直白名称。下表中的术语含义固定：

| 名称 | 含义 |
|---|---|
| Run | 用户一次输入、按钮点击或表单提交触发的一次后端执行 |
| Turn | 用户和助手的一轮交互；一次 Turn 通常对应一个 Run |
| `threadId` | 一个页面会话的唯一标识，也是 LangGraph Checkpoint 的会话键 |
| `runId` | 一次 Run 的唯一标识，同时作为幂等键 |
| `trace_id` | 后端生成的调用链标识，只用于耗时和错误查询 |
| Checkpoint | LangGraph 保存的“执行到了哪里以及当前数据是什么” |
| DAG | 按明确步骤和条件运行的业务流程图 |
| ReAct | 模型通过思考当前输入并选择 Tool 的 Agent 运行方式 |
| Scenario Tool | 一个完整业务场景的入口，例如智能分流或知识推荐 |
| Atomic Tool | 只完成一个可复用小能力的 Tool |
| Subgraph | 被其他 LangGraph 调用的内部子流程，例如商品推荐 |
| Node | LangGraph 中执行一个明确步骤的函数 |
| Delegate | 隔离模型、外围 Agent、外部接口或数据库的调用对象 |
| AG-UI | Agent 后端与用户界面之间的开放流式事件协议 |
| Interrupt | Graph 暂停执行，等待用户选择、填写或确认 |
| Composition Root | 应用启动时唯一负责创建对象并连接依赖的装配文件 |

## 3. 项目目标与非目标

### 3.1 项目目标

必须交付以下能力：

- 按钮或自然语言触发“智能分流”和“知识推荐”。
- 可运行的 ReAct 场景路由器。
- 两个确定性业务 LangGraph。
- 主服务内部的商品推荐 Subgraph。
- LangGraph 暂停、恢复和 24 小时 Checkpoint。
- Vue 3 正式前端，直接调用真实 LangGraph 后端，不使用 Mock Backend。
- AG-UI 标准事件及采购领域扩展事件。
- 外围 Agent 的流式与非流式 Delegate。
- OpenAI 兼容 Model Delegate 和测试专用 Mock Model。
- OpenGauss 数据库 Delegate。
- 系统自动生成、更新的个人长期记忆。
- 后端全链路调用耗时记录。
- 原生虚拟机和 Docker 两种部署方式。
- 严格分离的契约、集成、端到端和并发冒烟测试。

### 3.2 首次试运行目标

- 首次试运行以业务功能可用为验收目标。
- 代码必须保持无服务端本地会话状态，允许后续横向扩展。
- 首次上线不以 500 请求/秒和 5000 在线用户作为通过门槛。
- 后续达到该规模前，必须补充容量测试，并重新评估 Redis、连接池和部署实例数量。

### 3.3 明确不做

本次不得实现：

- 自研编排引擎、节点运行时或 Graph DSL。
- Command Bus 或 CQRS 框架。
- 动态 Tool Registry、运行时反射扫描或任意字符串 import。
- Manifest、插件安装、插件生命周期或数据库动态注册。
- Graph、Tool、Schema 的业务版本体系。
- Event Store、Outbox、后台任务队列或独立 SSE 事件服务。
- Redis 首版依赖。
- Kubernetes、OpenTelemetry、Prometheus 或 Grafana。
- 调用链监控页面或监控查询 HTTP 接口。
- 独立部署的商品推荐 Agent 服务。
- 独立数据库服务。
- 向量数据库、Embedding 或知识图谱式长期记忆。
- 历史会话列表、会话搜索、重命名和删除界面。
- Safari、Firefox、Edge 和手机浏览器兼容验收。
- 滑词触发知识推荐。
- 一次输入多个商品并行处理。

## 4. 已锁定的技术决策

| 主题 | 决策 |
|---|---|
| 编排 | LangGraph 是唯一业务流程引擎 |
| LangChain | 用于模型、消息、Tool 和 ReAct，不承担业务状态持久化 |
| ReAct | 只负责自然语言场景路由，不能绕过业务 DAG |
| 业务流程 | 智能分流和知识推荐使用确定性 LangGraph |
| 商品推荐 | 主服务内部 LangGraph Subgraph，不单独部署 |
| 前端 | Vue 3 + TypeScript + Vite + Ant Design Vue |
| Agent UI 协议 | AG-UI 标准事件 + 采购 `CUSTOM` 事件 |
| HTTP | 一个 POST 请求通过 SSE 返回该 Run 的 AG-UI 流 |
| 状态 | OpenGauss Checkpoint，正式环境禁止只用内存 |
| 数据访问 | 所有数据库操作必须经过数据库 Delegate |
| 外围能力 | 公共 HTTP 能力 + 每个能力一个明确 Delegate |
| 模型 | `ModelDelegate`；先实现 OpenAI 兼容接口，可配置本地模型 |
| Redis | 首版不依赖，知识使用进程内 TTL 缓存 |
| 幂等 | AG-UI `runId` 直接作为幂等键 |
| 并发 | 同一 `threadId` 串行；同一用户可并行多个 `threadId` |
| Checkpoint | 可恢复 24 小时；代码部署更新时结束旧场景，不做兼容版本 |
| 长期记忆 | 个人 JSON 记忆，自动更新，只用于非关键个性化 |
| 监控 | 后端全链路 100% 保存到 OpenGauss，不做页面和查询 API |
| 浏览器 | 只正式支持桌面版 Chrome |
| 部署 | 同时提供虚拟机原生部署和 Docker 部署 |
| 测试 | 不要求细粒度单元测试；严格要求契约、集成和 E2E 测试 |
| 注释 | 高可读性代码，复杂逻辑必须有详细中文注释 |

## 5. 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Vue 3 + TypeScript + Ant Design Vue                         │
│ AG-UI 协议适配 │ 采购业务组件 │ PurchaseFormBridge            │
└──────────────────────────┬──────────────────────────────────┘
                           │ POST + SSE / AG-UI
┌──────────────────────────▼──────────────────────────────────┐
│ FastAPI                                                     │
│ 身份/上下文 │ Run 幂等/租约 │ AG-UI 适配 │ Trace Collector    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│ 场景分发                                                    │
│ 自然语言 -> ReAct -> 静态目录 │ 按钮 -> 静态目录（绕过 ReAct）│
└──────────────────────────┬──────────────────────────────────┘
                           │ 只启动 Scenario Tool
                ┌──────────┴──────────────┐
                │                         │
┌───────────────▼─────────────┐ ┌─────────▼──────────────────┐
│ 智能分流 Scenario Tool      │ │ 知识推荐 Scenario Tool     │
│ 智能分流 LangGraph          │ │ 知识推荐 LangGraph         │
│ └─ 商品推荐 Subgraph        │ │ 精确匹配，不调用模型       │
└───────────────┬─────────────┘ └─────────┬──────────────────┘
                │                         │
┌───────────────▼─────────────────────────▼───────────────────┐
│ Delegate                                                    │
│ Model │ 外围 Agent │ 搜索 │ 知识 │ 排队 │ Database/Checkpoint│
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
┌───────────────▼─────────────┐ ┌─────────▼──────────────────┐
│ OpenGauss                   │ │ 公司外围服务与模型接口     │
│ Checkpoint/会话/记忆/Trace  │ │ HTTP 或流式 HTTP           │
└─────────────────────────────┘ └────────────────────────────┘

贯穿每个 Run：ExecutionContext -> 父子 Span -> Turn 结束批量写 Trace
每个 Turn 响应后：受管理异步任务 -> Model Delegate -> 个人记忆 JSON
```

### 5.1 各部分职责

| 部分 | 只负责 | 不负责 |
|---|---|---|
| Vue 3 前端 | 展示 AG-UI 事件、收集用户输入、执行前端加购和页面跳转 | 决定 Graph 节点、解释 Agent 原始协议 |
| FastAPI 接入 | 身份、请求校验、Run 生命周期、SSE、错误边界 | 编写采购业务判断 |
| 场景分发 | 让按钮直达 Scenario Tool，让自然语言进入 ReAct | 执行 IOI、栏目等采购判断 |
| ReAct 路由 | 根据自然语言选择受支持场景 | 直接执行 IOI、栏目、搜索或数据库操作 |
| Scenario Graph | 关键采购业务步骤、条件分支、暂停和恢复 | 直接拼接 HTTP 或 SQL |
| Delegate | 外部协议转换、超时、重试、数据库读写 | 决定业务流程下一步 |
| AG-UI 适配 | 将内部事件转换成稳定的标准或采购自定义事件 | 暴露 LangGraph 原始状态 |
| Trace | 记录调用父子关系、耗时、状态和重试 | 改变业务执行结果 |
| 记忆更新 | Turn 后自动维护个人 JSON，为非关键个性化提供上下文 | 覆盖当前输入或决定关键业务分支 |

## 6. 技术版本基线

后端已在 2026-08-05 通过 `uv` 完成兼容解析并提交 `uv.lock`；下表同时记录允许版本线和
本次实际锁定版本。以后升级必须重新运行全部门禁，不能只修改版本号。Vue 3 前端使用
独立的 `package-lock.json` 锁定并单独验收。

### 6.1 后端版本线

| 技术 | 允许版本线 | 当前锁定/执行版本 |
|---|---|---|
| Python | `>=3.12,<3.13` | `3.12.13` |
| LangGraph | `>=1,<2` | `1.2.10` |
| LangChain | `>=1,<2` | `1.3.14` |
| langchain-core | `>=1,<2` | `1.5.3` |
| langchain-openai | `>=1,<2` | `1.4.1` |
| LangGraph PostgreSQL Checkpointer | `>=3,<4`；必须另验 OpenGauss | `3.1.1` |
| FastAPI | `<1` | `0.141.1` |
| Uvicorn | `<1` | `0.52.1` |
| Pydantic | `>=2,<3` | `2.13.4` |
| pydantic-settings | `>=2,<3` | `2.14.2` |
| AG-UI Python SDK | 锁文件解析的兼容稳定版 | `0.1.19` |
| HTTPX | `<1` | `0.28.1` |
| Psycopg / psycopg-pool | `>=3,<4` | `3.3.4` / `3.3.1` |
| Tenacity | `>=9,<10` | `9.1.4` |
| uv | 当前开发工具稳定版 | `0.11.1` |

### 6.2 前端版本线

| 技术 | 版本线 |
|---|---|
| Node.js | 24 LTS 最新补丁版 |
| npm | Node 24 配套稳定版 |
| Vue | 3.x，使用同一 Vue 运行时 |
| TypeScript | 开发时最新稳定兼容版 |
| Vite | 开发时最新稳定兼容版 |
| Ant Design Vue | 4.x 最新稳定兼容版 |
| Zod | 最新稳定兼容版 |

### 6.3 测试与质量工具

| 技术 | 用途 |
|---|---|
| pytest / pytest-asyncio | 后端契约和集成测试 |
| Playwright | Chrome 端到端测试 |
| Ruff | Python 格式和静态检查 |
| mypy | Python 类型检查 |
| ESLint / Prettier | TypeScript 静态检查与格式化 |
| k6 | 并发冒烟测试 |

### 6.4 锁定规则

1. 后端必须提交 `pyproject.toml` 和 `uv.lock`。
2. 前端必须提交 `package.json` 和 `package-lock.json`。
3. 所有安装和生产构建必须使用锁文件的 frozen 模式。
4. Vue 与 Ant Design Vue 必须通过锁文件保持可重复安装，并完成浏览器验收。
5. LangChain、langchain-core、langchain-openai 与 LangGraph 必须一起解析，不能分别强制安装各自最高版本。
6. AG-UI Python 与 TypeScript SDK 必须完成协议互通测试。
7. 若最新版本不兼容 Python 3.12、Node 24、OpenGauss 或其他核心依赖，退回最近的稳定兼容版，并在 `README.md` 记录原因。
8. 当前本机 Python 3.14 和 Node 25 均不得作为生产版本依据。

### 6.5 开发前兼容性验证

创建脚手架前必须先完成并记录：

- LangGraph 1.x 的 Subgraph、Interrupt、Checkpoint 与异步流式 API 验证。
- LangChain 1.x ReAct Agent 与 Scenario handoff Tool 验证。
- AG-UI Python SDK、Vue SSE 适配器、LangGraph 流和 `CUSTOM` 事件验证。
- Ant Design Vue 与 Vue 3 验证。
- Python 3.12 下 Psycopg 与预期 OpenGauss 版本的驱动验证；没有真实数据库时标记为未验证。

## 7. 目标目录结构

目录必须按下列结构创建。每个目录后面的注释是该目录唯一职责，不得把不相关代码混入。

```text
procumentagent_lite/                              # 项目根目录，只放跨前后端的配置、文档和部署入口
├── README.md                                     # 项目入口、当前状态、运行方式和生产接入状态
├── docs/                                         # 唯一的项目设计与开发文档目录
│   └── DEVELOPMENT.md                            # 本文，后续开发的唯一权威规范
├── backend/                                      # Python 后端生产工程，禁止放前端和测试代码
│   ├── pyproject.toml                            # Python 依赖、Ruff、mypy 和 pytest 配置
│   ├── uv.lock                                   # 后端精确依赖锁
│   ├── Dockerfile                                # 不包含测试代码的后端生产镜像
│   ├── migrations/                               # OpenGauss 显式 SQL 迁移与回滚脚本
│   └── src/                                      # 后端生产源码根目录
│       └── procurement_assistant/                # 后端唯一 Python 包
│           ├── main.py                           # 稳定启动入口，只调用 business.bootstrap
│           ├── core/                             # 通用引擎，禁止反向 import business
│           │   ├── api/                          # FastAPI、SSE、身份、错误和会话接口
│           │   ├── config/                       # CoreSettings、模型端点等通用配置模型
│           │   ├── delegates/                    # 通用数据库、模型、HTTP 和流调用边界
│           │   │   ├── common/                   # 调用上下文、HTTP 客户端、流事件
│           │   │   ├── database/                 # Run、Action、Checkpoint、记忆和 Trace 数据访问
│           │   │   └── model/                    # 结构化模型和 ReAct 的通用实现
│           │   ├── domain/                       # ID、生命周期和通用错误
│           │   ├── memory/                       # 后台任务管理和 MemoryUpdater 接口
│           │   ├── observability/                # Span 收集、Checkpoint 计时和批量落库
│           │   ├── orchestration/                # Application、GraphRunner、运行上下文和等待原语
│           │   │   └── router/                   # ReAct 场景路由和场景切换协调
│           │   ├── protocol/                     # AG-UI 通用输入、事件信封和 SSE 适配
│           │   └── shared/                       # 时钟和 ID 生成器
│           └── business/                         # 采购业务，允许 import core
│               ├── administration/               # 发布前结束旧场景的业务管理命令
│               ├── bootstrap.py                  # 唯一业务装配入口
│               ├── config/                        # AppSettings 和 BusinessSettings
│               ├── delegates/                     # 采购外围 Agent 和服务适配器
│               │   ├── agents/                    # IOI、栏目、重复自采
│               │   └── services/                  # 搜索、知识缓存、排队
│               ├── domain/                        # 商品、栏目、预算和记忆领域模型
│               ├── interaction/                   # 业务操作、表单模型和等待点工厂
│               ├── memory/                        # 个人采购记忆更新实现
│               ├── prompts/                       # 每个业务模型任务一个 Prompt 文件
│               ├── protocol/                      # 商品、排队、页面跳转和快照策略
│               ├── registry/                      # 场景、模型任务、交互和 Atomic Tool 注册
│               ├── scenarios/                     # 业务 State、Node、Route、Graph
│               │   ├── knowledge/                 # 知识推荐及 definition.py
│               │   ├── smart_routing/             # 智能分流及 definition.py
│               │   └── subgraphs/                 # 商品推荐内部子图
│               └── tools/                         # 每个 Scenario/Atomic Tool 一个文件
├── frontend/                                     # Vue 3 前端生产工程，禁止放后端和测试代码
│   ├── package.json                              # 前端依赖与脚本
│   ├── package-lock.json                         # 前端精确依赖锁
│   ├── vite.config.ts                            # Vite 开发和构建配置
│   ├── tsconfig.json                             # TypeScript 严格模式配置
│   ├── Dockerfile                                # 前端静态文件生产镜像
│   └── src/                                      # 前端生产源码根目录
│       ├── main.ts                               # Vue 唯一启动入口和组件库装配
│       ├── App.vue                               # 顶层页面组合
│       ├── agui/                                 # AG-UI SSE、标准事件和采购事件解析
│       ├── assistant/                            # 场景入口、对话、表单、Action 和会话恢复
│       ├── procurement/                          # 商品组件、申购单和 PurchaseFormBridge
│       ├── config/                               # 前端环境配置和导航目标映射
│       ├── schemas/                              # Zod 运行时协议校验
│       └── styles.css                            # Ant Design Vue 的补充业务样式
├── test_support/                                 # 非生产的 Fake、固定数据和本地 Mock 装配
│   ├── fake_delegates/                           # 各外围 Agent、服务和数据库的可控 Fake
│   ├── fake_model/                               # 不调用真实模型的确定性 Model Delegate
│   ├── fixtures/                                 # 全路径测试使用的固定 JSON 数据
│   └── local_app/                                # 本地 Mock 模式启动入口，不得进入生产构建
├── tests/                                        # 与生产代码严格分开的全部测试
│   ├── contract/                                 # AG-UI、HTTP 和 Delegate 契约测试
│   ├── integration/                              # LangGraph 全业务路径和状态恢复测试
│   ├── e2e/                                      # Playwright 驱动的前后端真实交互测试
│   └── performance/                              # k6 基础并发和长连接冒烟测试
├── deploy/                                       # 两种正式部署方式及配置模板
│   ├── systemd/                                  # 虚拟机原生部署服务定义
│   ├── nginx/                                    # 静态前端和 SSE 代理示例
│   └── docker/                                   # Docker Compose 和环境模板
└── scripts/                                      # 格式检查、测试、构建、迁移和验收入口脚本
```

### 7.1 严格目录规则

- `backend/src` 和 `frontend/src` 只能包含生产代码。
- 生产代码禁止 import `tests` 或 `test_support`。
- `test_support` 可以 import 生产接口，以实现 Fake；反向依赖禁止。
- 生产 Docker 镜像和发布包必须排除 `tests` 与 `test_support`。
- Graph 节点不得直接 import HTTPX、Psycopg 或具体数据库实现。
- API 层不得 import 某个具体外围 Agent HTTP 实现。
- `domain` 不得依赖 FastAPI、LangGraph、LangChain、AG-UI、HTTPX 或 Psycopg。
- `shared` 不是杂物目录。无法证明被三个以上模块复用的代码不得放入。
- 每个 Scenario Tool 和 Atomic Tool 必须各自使用一个文件。
- Prompt 禁止以内联长字符串散落在 Python 文件中。

## 8. 依赖方向与装配

允许的依赖方向：

```text
core/api / core/protocol
      ↓
core/orchestration
      ↓
      ↑
core 和 Business 的具体 Delegate

business/bootstrap.py 在最外层创建并连接所有对象
```

具体要求：

1. `business/bootstrap.py` 是唯一知道全部具体实现的位置。
2. Graph、Node 和 Tool 的构造函数只接收所需 Delegate，不读取全局容器。
3. 禁止 Service Locator、可变全局 Registry 和运行时依赖查找。
4. Core 的通用接口放在 Core，采购外围 Delegate 接口和实现放在 `business/delegates/`。
5. FastAPI `Depends` 只用于 HTTP 级身份和请求上下文，不作为全局业务依赖容器。
6. 场景依赖通过 `definition.py` 中的强类型依赖对象注入；不使用 Service Locator。
7. 测试通过构造函数注入 Fake，不允许 monkey patch 生产模块的全局对象。
8. Core 的场景、Action 输入和记忆更新均依赖 Protocol/Registry；Core 代码中不得出现
   `procurement_assistant.business` 字符串或导入。

## 9. 标识、身份与页面上下文

### 9.1 标识规则

| 标识 | 生成方 | 用途 | 是否可复用 |
|---|---|---|---|
| `user_id` | 前端页面上下文 | 个人会话与记忆归属 | 同一用户稳定 |
| `threadId` | 前端 | 会话与 Checkpoint 键 | 一个会话内稳定 |
| `runId` | AG-UI 前端 Client | 本次执行和幂等键 | 不得用于不同 Run |
| `trace_id` | 后端 | 全链路耗时查询 | 每次后端接收 Run 新建 |
| `action_id` | 后端 | 一次性用户 Action | 只能成功消费一次 |
| `interrupt_id` | LangGraph | 暂停与恢复定位 | 只对当前 Checkpoint 有效 |

标识使用不可预测的 UUID/ULID 类值，不编码 Graph 节点、业务参数或用户隐私。

### 9.2 用户身份

- 前端通过 `X-User-ID` 请求头直接传入 `user_id`。
- 当前版本不验签，这是已确认决策。
- 后端仍必须校验非空、长度和允许字符。
- 每次读取 `threadId`、`runId`、`action_id` 时都必须同时验证其 `user_id` 归属。
- 页面上下文绝不能参与身份鉴权。

### 9.3 页面上下文

通过 AG-UI `forwardedProps.pageContext` 传入：

```json
{
  "regionCode": "CN-SH",
  "locale": "zh-CN",
  "currentPage": "/procurement"
}
```

- `regionCode` 由前端调用其他服务获得后直接提供。
- 区域缺失时智能分流 Graph 必须追问。
- `locale` 默认 `zh-CN`。
- `currentPage` 只用于上下文和日志，不参与授权。

## 10. HTTP 与 AG-UI 协议

### 10.1 公开端点

首版只公开以下业务端点：

| 方法与路径 | 用途 |
|---|---|
| `POST /api/v1/agent` | 接收 AG-UI `RunAgentInput`，以 SSE 返回 AG-UI 事件 |
| `GET /api/v1/sessions/{thread_id}/snapshot` | 页面刷新后恢复当前会话快照 |
| `GET /health/live` | 进程存活检查 |
| `GET /health/ready` | 配置和必要依赖就绪检查 |

不得增加监控查询端点。Action、表单提交和场景按钮都复用 `POST /api/v1/agent`。

### 10.2 Run 输入

标准文字输入使用 AG-UI `messages`。最后一条用户消息是本次自然语言输入。

按钮、Action 和表单使用 `forwardedProps.procurementInput`：

```json
{
  "threadId": "thread_...",
  "runId": "run_...",
  "messages": [],
  "state": {},
  "tools": [],
  "context": [],
  "forwardedProps": {
    "pageContext": {
      "regionCode": "CN-SH",
      "locale": "zh-CN",
      "currentPage": "/procurement"
    },
    "procurementInput": {
      "type": "scenario_trigger",
      "scenarioId": "smart_routing"
    }
  }
}
```

`procurementInput.type` 是严格区分的联合类型：

| 类型 | 必填数据 | 用途 |
|---|---|---|
| `scenario_trigger` | `scenarioId` | 点击场景入口，准确绕过 ReAct |
| `action` | `actionId`, `data` | 点击换一批、重试、结束、跳转等动作 |
| `form_submit` | `actionId`, `values` | 提交 Graph 请求的结构化表单 |

规则：

- 自然语言输入不得同时携带 `procurementInput`。
- 自然语言 Run 必须以一条新的用户消息结尾；后端只把这条新消息作为本次输入，历史记录从 OpenGauss 加载，不信任客户端重写的旧消息。
- Action、Form 和纯按钮触发允许 `messages` 为空。
- 当前版本要求客户端 `tools` 为空；可用 Scenario Tool 只由服务端静态目录决定，拒绝客户端注入 Tool。
- 当前版本要求客户端 `state` 和 `context` 为空；业务状态只从 Checkpoint 读取，页面区域只从已声明的 `forwardedProps.pageContext` 读取。
- `forwardedProps` 禁止未声明字段，`scenarioId` 只能来自服务端允许列表。
- `runId` 是幂等键；重复 `runId` 不得再次执行。
- `actionId` 必须属于当前用户、当前 `threadId` 和当前有效 Checkpoint。
- 表单字段由服务端 Action 对应的 Pydantic 模型重新校验，不能信任前端。
- 入口必须先检查 `runId` 幂等，再读取或校验 Action。即使网络重放的 Action 正文已
  损坏，只要 `runId` 已登记，也应稳定返回重复 Run，不能重新解释成另一种用户错误。
- Action/Form 值的纯 Pydantic 校验必须在消费前完成；校验失败不得改变 Action 状态，
  用户修正后仍可使用原按钮。最终消费仍在数据库短事务中重新锁定并复查，防止竞态。

### 10.3 SSE 响应

- 响应 `Content-Type` 必须为 `text/event-stream; charset=utf-8`。
- 每个事件必须是有效 AG-UI 事件。
- 第一条运行事件是 AG-UI `RUN_STARTED`。
- 正常结束必须发送 `RUN_FINISHED`。
- 失败必须发送安全的 `RUN_ERROR`，内部异常不得直接返回。
- 文字流使用 AG-UI `TEXT_MESSAGE_START/CONTENT/END`。
- Tool 调用可使用 AG-UI `TOOL_CALL_*`，但不得显示模型隐藏推理。
- 采购特有 UI 使用 AG-UI `CUSTOM`。
- 不得把 LangGraph 原始 state、checkpoint、节点名或外围 Agent 原始 chunk 直接透传。

### 10.4 采购自定义事件

每个事件使用 AG-UI `CUSTOM`，`name` 固定，`value` 由 Pydantic 与 Zod 双端校验。

| `name` | 作用 |
|---|---|
| `procurement.scene` | 当前场景开始、切换、结束或过期 |
| `procurement.status` | 可向用户展示的阶段状态，不包含内部推理 |
| `procurement.options` | 栏目或其他单选候选 |
| `procurement.form` | 需要用户填写的字段 |
| `procurement.products` | 商品列表、分页信息和前端加购数据 |
| `procurement.actions` | 当前 Checkpoint 有效的操作集合 |
| `procurement.queue` | 自定义采购排队数量和固定文案 |
| `procurement.navigation` | 前端固定目标跳转命令 |
| `procurement.retry` | 自动重试失败后允许用户再次触发 |
| `procurement.agent_stream` | 允许展示的外围 Agent 进度或文字增量 |

所有采购事件至少包含：

```json
{
  "schema": "procurement-ui-v1",
  "threadId": "thread_...",
  "runId": "run_...",
  "eventId": "event_...",
  "sequence": 1,
  "payload": {}
}
```

说明：

- 这里只给前后端协议整体使用 `v1`，不为每个 Graph、Tool 或 Block 单独增加版本号。
- `sequence` 只表示当前 Run 内事件顺序，不是业务版本。
- 事件 payload 禁止任意 HTML、脚本或未声明字段。

### 10.5 Options 事件

```json
{
  "name": "procurement.options",
  "value": {
    "schema": "procurement-ui-v1",
    "threadId": "thread_...",
    "runId": "run_...",
    "eventId": "event_...",
    "sequence": 4,
    "payload": {
      "title": "请选择采购栏目",
      "actionId": "action_...",
      "multiple": false,
      "options": [
        {
          "optionId": "column_...",
          "label": "办公电脑",
          "description": "适用于研发办公"
        }
      ]
    }
  }
}
```

栏目识别 Agent 只调用一次。多个栏目全部保存在 Checkpoint；用户选择后按 `optionId` 从已保存结果中匹配，禁止再次调用栏目识别 Agent。

### 10.6 Form 事件

表单只允许预定义字段类型：`text`、`number`、`select`。禁止后端下发任意 Vue 组件名。

每个表单包含：

- `actionId`。
- 标题。
- 字段 ID、标签、类型、必填标记和候选项。
- 可选的最小值、最大值和长度限制。

前端提交后，后端必须按该 `actionId` 绑定的 Pydantic 输入模型再次验证。

### 10.7 Products 事件

商品事件必须使用明确字段，不得依赖字符串解析：

```json
{
  "name": "procurement.products",
  "value": {
    "schema": "procurement-ui-v1",
    "threadId": "thread_...",
    "runId": "run_...",
    "eventId": "event_...",
    "sequence": 7,
    "payload": {
      "title": "为你推荐",
      "page": 1,
      "pageSize": 3,
      "hasNext": true,
      "products": [
        {
          "productId": "product_...",
          "name": "研发办公笔记本",
          "price": 8999,
          "currency": "CNY",
          "imageUrl": null,
          "deliveryText": "2 天发货",
          "badges": ["电商在售", "部门热采"],
          "metadata": {}
        }
      ]
    }
  }
}
```

- 默认 `pageSize=3`，必须可配置。
- 商品加购由前端处理，事件中不签发后端加购 Action。
- `metadata` 只容纳已声明为可展示的搜索结果扩展字段，禁止放模型推理。

### 10.8 Navigation 事件

后端只返回固定目标标识，不返回任意 URL：

```json
{
  "name": "procurement.navigation",
  "value": {
    "schema": "procurement-ui-v1",
    "threadId": "thread_...",
    "runId": "run_...",
    "eventId": "event_...",
    "sequence": 9,
    "payload": {
      "target": "custom_purchase",
      "params": {}
    }
  }
}
```

允许的 `target` 只有：

- `ioi_purchase`
- `self_purchase`
- `custom_purchase`

实际 URL 由 Vue 3 环境配置映射。后端、模型和外围 Agent 均不能产生任意跳转 URL。

### 10.9 会话快照

`GET /api/v1/sessions/{thread_id}/snapshot` 只返回当前用户有权访问的会话，内容包括：

- 历史用户消息与助手可展示消息。
- 当前活动场景。
- 场景状态：运行中、等待用户、已结束或已过期。
- 最近一个仍有效的 Form、Options 和 Actions。
- 已选栏目和当前商品页等恢复 UI 必需数据。
- Checkpoint 到期时间。

快照不得返回：

- LangGraph 内部序列化数据。
- Prompt、模型隐藏推理或 Delegate 凭据。
- 长期记忆原始 JSON。
- Trace 明细。
- 历史 `procurement.scene`、`procurement.navigation` 或 `procurement.agent_stream` 事件。
  场景使用数据库顶层状态恢复；导航是一次性副作用，刷新后绝不能再次执行；流进度已经
  结束，重放会误导用户。

场景已经完成、中止、过期或部署清理后，快照不得返回历史 Form/Options/Actions。UI
块表用于审计并不会随 Action 失效而删除，因此快照投影必须依据当前是否存在活动场景
过滤交互块，不能把“曾展示过”误当作“现在仍可点击”。

快照投影算法属于 Core，但可恢复事件名称由 Business 的
`business/protocol/snapshot.py` 注入 `SnapshotBlockPolicy`。因此新增业务事件时，只需在
Business 策略中决定它是否可恢复，不需要修改 Core 的会话接口。

### 10.10 断线行为

- 浏览器断开 POST SSE 后，不保证当前正在运行的外围调用继续执行。
- 当前实现会取消本次 Run，把 Run 标记为 `failed/CLIENT_DISCONNECTED`，并把已经创建的
  活动场景标为 `aborted`、使其 Action 失效，避免留下页面无法可靠恢复的半成品等待点。
- 最后成功 Checkpoint 和历史记录继续保留用于审计，但该已中止场景不再恢复；用户重新
  打开页面后从新的场景开始。进程意外重启与浏览器主动断线不同，仍按 24 小时规则恢复。
- 关键外部写操作若未来出现，必须先增加独立幂等设计；不得假定所有操作都可重复。
- 当前已确认的外围 Agent、搜索、知识和排队调用按只读能力设计。

### 10.11 其余采购事件的固定 payload

`procurement.scene`：

```json
{
  "scenarioId": "smart_routing",
  "status": "waiting",
  "reason": null
}
```

- `scenarioId` 只允许静态 Scenario Catalog 中的值。
- Scene 事件和快照把已经通过 Catalog 校验的 `scenarioId` 作为非空字符串交给前端通用
  展示，不在恢复协议中重复写死当前两个场景；页面主动触发入口仍使用明确允许列表。这样
  新增 DAG 时不会因纯展示协议的枚举遗漏而拒绝合法事件，也不会放宽启动未知场景的权限。
- `status` 只允许 `running`、`waiting`、`completed`、`aborted`、`expired`。
- `reason` 是可选安全原因码，不放异常堆栈。

`procurement.status`：

```json
{
  "code": "SEARCHING_PRODUCTS",
  "text": "正在为你查找商品…"
}
```

`code` 必须是前后端约定枚举；`text` 只用于展示，不得被前端解析为业务状态。

`procurement.form`：

```json
{
  "title": "请补充采购信息",
  "actionId": "action_...",
  "fields": [
    {
      "fieldId": "budgetAmount",
      "label": "预算金额",
      "type": "number",
      "required": true,
      "options": [],
      "min": 0,
      "max": null,
      "minLength": null,
      "maxLength": null
    }
  ],
  "submitLabel": "继续"
}
```

- `fieldId` 必须来自该等待点绑定的 Pydantic 输入模型允许字段。
- `select` 字段才允许非空 `options`；每项只有 `value` 和 `label`。
- 前端不得执行 payload 中的表达式；协议不提供正则、脚本或组件名。

`procurement.actions`：

```json
{
  "title": "你还可以",
  "groupId": "action_group_...",
  "actions": [
    {
      "actionId": "action_...",
      "kind": "next_page",
      "label": "换一批",
      "style": "default"
    },
    {
      "actionId": "action_...",
      "kind": "end_recommendation",
      "label": "结束本次推荐",
      "style": "default"
    }
  ]
}
```

允许的首批 `kind`：

- `next_page`
- `append_product`
- `other_procurement_mode`
- `end_recommendation`
- `go_self_purchase`
- `go_custom_purchase`
- `retry`
- `confirm_scene_switch`
- `cancel_scene_switch`

每个 Action 的含义由服务端已保存记录决定，前端不能用 `kind` 伪造未签发操作。`style` 只允许 `primary`、`default`、`danger`。

`procurement.queue` 只在数量大于 0 时发送：

```json
{
  "count": 12,
  "text": "前面还有12单在采购受理中哦～，审批完成后，采购将按顺序为您处理！"
}
```

`procurement.retry`：

```json
{
  "actionId": "action_...",
  "errorCode": "UPSTREAM_TEMPORARILY_UNAVAILABLE",
  "message": "暂时没有处理成功，可以从当前步骤重试。",
  "label": "重试"
}
```

重试 Action 仍保存在 `pending_actions`，不是不受校验的快捷入口。

`procurement.agent_stream`：

```json
{
  "callId": "call_...",
  "delegateId": "column_recognition",
  "attempt": 1,
  "streamSequence": 2,
  "kind": "text_delta",
  "content": "正在分析可选栏目"
}
```

- 向前端只允许 `progress`、`text_delta`、`status` 三种 `kind`。
- 结构化 `final_result` 由后端校验并写 Graph，不通过这个事件暴露内部原始 JSON。
- `content` 是已获准展示的普通文本，禁止 HTML 和隐藏推理。

### 10.12 HTTP 错误与 SSE 错误边界

只有请求通过入口校验、幂等检查和 thread 租约获取后才打开 SSE：

| 阶段 | 返回方式 |
|---|---|
| JSON/身份/归属/Action 校验失败 | HTTP 4xx + 固定 JSON 错误模型 |
| 相同 `runId` 已存在 | HTTP 409 + 现有 Run 状态和 snapshot 路径 |
| 同一 thread 正在执行 | HTTP 409 `THREAD_BUSY` |
| 全局过载保护拒绝 | HTTP 429/503，可带 `Retry-After` |
| SSE 已打开后的 Graph/Delegate 失败 | AG-UI `RUN_ERROR` 后正常关闭流 |

统一 JSON 错误只包含 `code`、`message`、`traceId` 和可选 `snapshotUrl`。不得返回数据库键、堆栈或其他用户资源是否存在的信息。

## 11. ReAct、Scenario Tool 与 Atomic Tool

### 11.1 三者的边界

本项目保留两类 Tool，但不建设动态插件系统：

| 类型 | 代表什么 | 当前谁可以调用 | 是否可以改变业务流程 |
|---|---|---|---|
| Scenario Tool | 一个完整场景的入口 | 顶层 ReAct 或按钮路由 | 只能启动对应 LangGraph，不能自己完成业务 |
| Atomic Tool | 一个可复用的小能力 | 明确允许使用它的 Graph 或未来场景内 Agent | 不能自行决定进入哪个场景 |

当前只有两个 Scenario Tool：

- `smart_routing`：启动智能分流 Graph。
- `knowledge_recommendation`：启动知识推荐 Graph。

Atomic Tool 只在以下任一条件成立时创建：

1. 同一能力被至少两个 Graph 或 Agent 复用。
2. 该能力需要作为 LangChain Tool 暴露给某个受约束的 ReAct。
3. 该能力有独立、稳定且值得单独测试的输入输出协议。

一个节点只调用一次的 Delegate 不再套一层 Atomic Tool。Atomic Tool 本身可以按需要调用外围 Agent、模型、长期记忆或普通外部服务，但仍须通过对应 Delegate，禁止在 Tool 中直接写 HTTP、SQL 或读取凭据。

当前两个已确认场景暂时没有满足上述条件的 Atomic Tool，因此 `ATOMIC_TOOL_REGISTRY` 可以为空；保留这一概念是为了未来可控扩展，不是要求先创建无用途的空壳类。

### 11.2 一个 Tool 一个文件

每个 Tool 必须是一个单独代码文件；一个文件只实现一个 Tool。例如：

```text
business/tools/
├── start_smart_routing.py
├── start_knowledge_recommendation.py
└── future_supplier_lookup.py
```

文件名、Python 对象名和目录中的 `tool_id` 必须能直接对应。禁止在一个 `tools.py` 中堆积多个 Tool。

### 11.3 简单静态目录

每个场景的 Tool 名称和给模型看的说明写在自己的
`scenarios/<scene>/definition.py` 的 `ScenarioDefinition` 中；
`business/registry/scenarios.py` 只负责把这些完整定义汇总成一张总清单。这样描述不在 Tool
类里，新增能力时既能从汇总文件看到所有定义，也能在场景目录中连续阅读依赖、Tool 和 Graph。

推荐结构如下；实际开发可按最终 LangChain 1.x API 调整语法，但不得改变其静态、显式和易读的原则：

```python
def build_scenario_registry(*, smart_routing, knowledge_recommendation):
    """Business 的总清单，运行时由 Core 转换成只读 ScenarioRegistry。"""

    return ScenarioRegistry((smart_routing, knowledge_recommendation))

ATOMIC_TOOL_REGISTRY = {}
```

这里的“注册”只是开发人员新增一条普通 Python 配置：

1. 新建一个 Tool 文件和对应场景的 `definition.py`。
2. 在 `business/registry/scenarios.py` 中显式增加定义参数。
3. 在 `business/bootstrap.py` 中为该 Tool/Graph 装配强类型依赖。

不得使用运行时目录扫描、反射、数据库配置、聊天命令、任意 import 字符串、Manifest 或可变全局 Registry。目录只在进程启动时构造一次，并以只读对象提供给路由器。

### 11.4 ReAct 如何选择场景

顶层 ReAct 只接收 Business `ScenarioRegistry` 中的 Scenario Tool 描述。模型根据每个 Tool
的描述选择场景，因此描述必须写清楚“何时使用”和“不适用的情况”。Atomic Tool 和 Delegate
不得暴露给顶层 ReAct。

自然语言入口按以下顺序执行：

```text
用户文字
  -> 顶层 ReAct 读取可用 Scenario Tool 描述
  -> 选择且只选择一个 Scenario Tool
  -> Scenario Tool 创建场景实例
  -> 对应确定性 LangGraph 接管后续流程
```

限制：

- ReAct 只做场景选择，不做 IOI、栏目、自采或商品判断。
- ReAct 不得直接输出采购结论、页面地址或外围调用参数。
- ReAct 未能可靠选择场景时，返回简短澄清问题，不猜测执行。
- ReAct 的 Tool 调用参数只能包含原始用户文字和已校验页面上下文。
- Scenario Tool 不接受模型自由生成的查询正文。它从服务端 `ExecutionContext.original_user_text` 读取本次原文；模型只决定调用哪个 Tool，因此知识 key 不会被 Tool 参数改写。
- 用户点击场景按钮时，根据 `scenarioId` 直接查静态目录并启动场景，完全绕过 ReAct。
- 场景启动后隐藏场景入口按钮；当前场景结束、过期或被中止后才重新显示。

未来增加新 DAG 时，新增 Scenario Tool 和目录项即可让 ReAct看到它。是否允许某个新 DAG 使用 Atomic Tool，必须由该 DAG 的代码显式注入，不能让模型看到系统全部能力。

### 11.5 场景内切换

同一 `threadId` 同时只能有一个活动场景。场景执行期间收到明显指向其他场景的自然语言时：

1. 路由器只生成“是否切换”的候选，不立即终止当前 Graph。
2. 后端发出带一次性 `actionId` 的确认与取消按钮。
3. 用户取消后，恢复原场景及原等待状态。
4. 用户确认后，把原场景标为 `aborted`，使其全部旧 Action 失效，再创建新场景实例。

按钮和表单提交始终优先解释为当前 Graph 的恢复输入，不再进行场景识别。普通补充文字若正是当前节点所需内容，也应先交给当前 Graph；只有路由器明确判断用户在请求其他场景时才询问切换。

## 12. LangGraph 运行模型

### 12.1 场景实例、Run 和 Checkpoint

三个概念不能混用：

| 对象 | 生命周期 | 示例 |
|---|---|---|
| 场景实例 | 从进入某个场景到完成、中止或过期，可跨多个 Turn | 一次完整的智能分流过程 |
| Run | 一次 HTTP 输入触发的执行 | 提交栏目选择后继续执行 |
| Checkpoint | LangGraph 在节点边界保存的状态 | 正在等待用户选择栏目 |

后端为每次场景启动生成内部 `scenario_instance_id`。LangGraph 使用：

- `thread_id = threadId`
- `checkpoint_ns = scenario_instance_id`

这样同一用户可以使用不同 `threadId` 并行运行多个智能分流场景，同一会话内的新场景也不会覆盖旧场景的历史 Checkpoint。前端不需要理解 `checkpoint_ns`。

### 12.2 State 是什么

State 是 Graph 在步骤之间保存的一份有明确字段的记录，可以理解为“当前流程表单加执行位置”。它不是任意字典，更不能保存 Delegate、数据库连接、模型客户端或函数对象。

每个 Scenario 和 Subgraph 都定义自己的 Pydantic State。Pydantic 会在开发阶段和边界处检查字段类型。示意：

```python
class SmartRoutingState(BaseModel):
    scenario_instance_id: str
    status: Literal["running", "waiting", "completed", "aborted", "expired"]
    product_name: str | None = None
    purchase_purpose: str | None = None
    budget_amount: Decimal | None = None
    currency: str | None = None
    region_code: str | None = None
    column_candidates: list[ColumnCandidate] = Field(default_factory=list)
    selected_column: ColumnCandidate | None = None
    recommendation: RecommendationState | None = None
    wait_request: WaitRequest | None = None
```

节点读取当前 State，并只返回本次改变的字段。例如：

```python
async def select_single_column(state: SmartRoutingState) -> dict[str, object]:
    selected = state.column_candidates[0]
    return {"selected_column": selected, "wait_request": None}
```

上例不是直接修改数据库。LangGraph 合并返回值并通过 Checkpointer 保存。字段必须具备清楚的业务名字；禁止使用 `data`、`extra`、`temp` 等无法判断内容的万能字段。正式代码文件必须显式 `from pydantic import BaseModel, Field`，列表、字典必须使用 `Field(default_factory=...)`，不得使用可变默认值。

### 12.3 运行时上下文

不需要恢复、也不得写入 Checkpoint 的对象放入只对本次 Run 有效的 `ExecutionContext`：

- `user_id`、`thread_id`、`run_id` 和 `trace_id`。
- 已校验页面上下文。
- 当前总截止时间和剩余时间计算器。
- AG-UI 事件发送器。
- Trace 收集器。

Delegate 通过节点构造函数显式注入。不得把依赖容器放进 State，也不得让节点按字符串从全局对象中寻找 Delegate。

### 12.4 等待用户输入

需要用户填写、选择或确认时，Graph 使用 LangGraph `interrupt()`，不使用等待循环，也不保持 HTTP 连接或数据库事务。

统一过程为：

```text
准备等待内容
  -> State 保存 WaitRequest 和候选数据
  -> interrupt() 返回给运行器
  -> 运行器持久化一次性 Action 并发送 Form/Options/Actions 事件
  -> 本次 Run 结束
  -> 用户稍后用新 runId 提交 actionId
  -> 校验并消费 Action
  -> Command(resume=...) 恢复原 Graph
```

`WaitRequest` 至少包含：

- 稳定的 `wait_group_id`，以及预先生成并写入 Checkpoint 的各个 `action_id`。
- `kind`：`form`、`options`、`actions` 或 `confirmation`。
- 允许的操作及每个操作需要的输入模型 ID。
- 展示所需的结构化 payload。
- 创建时间和 24 小时到期时间。

Pydantic 输入模型负责校验用户填写的值。例如预算字段在进入 Graph 前必须已经转换成合法数字；Graph 不读取前端任意 JSON。

### 12.5 Action 生命周期

- 一个等待点可以签发多个 Action，例如换一批、追加商品、其他采购方式和结束。
- 每个按钮使用独立、不可预测的 `action_id`。
- 选择其中一个后，同组兄弟 Action 全部失效。
- Action 必须绑定 `user_id`、`thread_id`、`scenario_instance_id` 和对应等待点。
- Action 只能消费一次；过期、已消费、非当前等待点或不属于当前用户均拒绝。
- 后端先按 `runId` 查重，再预读取 Action 的静态输入模型和候选集合做纯校验；只有值合法
  才进入 `begin_run` 短事务锁定并消费。预读取不是授权凭证，事务仍要复查全部归属和状态。
- 前端加购按钮不属于后端 Action，不消费 Checkpoint，也不恢复 Graph。
- 恢复失败时不重新启用已消费 Action；后端依据最后成功 Checkpoint签发一次性“重试”Action。

为避免 LangGraph 恢复时重新执行 `interrupt()` 之前的代码导致重复副作用，等待节点必须把 `interrupt()` 放在可重复执行的安全位置。`wait_group_id` 和 Action ID 在前一个“准备等待”步骤生成并随 State 完成 Checkpoint；Graph 运行器根据中断结果用这些 ID 幂等 upsert 数据库记录。若进程在 Checkpoint 成功后、Action 落库前退出，快照或下一次恢复可用同一批 ID 补写，节点内不得直接插入 Action 表。

### 12.6 状态结束和过期

场景状态只能按以下方向变化：

```text
running <-> waiting -> completed
    |          |
    +----------+----> aborted
    +----------+----> expired
```

- `completed`、`aborted` 和 `expired` 是终态，不能恢复。
- Checkpoint 与 Action 默认 24 小时有效。
- 超过 24 小时后，首次读取时通过短事务把场景标为 `expired` 并拒绝恢复。
- 不运行常驻清理任务；当前决策是数据保留，只改变状态，不删除记录。
- 不设置 Graph、Tool 或 State 业务版本号。
- 每次代码部署前必须通过部署脚本把所有 `running`/`waiting` 场景标为 `expired`，并使其 Action 失效。由此直接结束旧代码创建的场景，不做兼容恢复。
- 单纯进程意外重启且未执行部署步骤时，24 小时内的同一代码 Checkpoint仍可恢复。

### 12.7 节点实现规则

每个节点必须满足：

1. 一个节点只表达一个清楚步骤，名称使用业务动词，例如 `recognize_columns`。
2. 输入从 State 和 `ExecutionContext` 显式读取。
3. 外部调用只经过注入的 Delegate。
4. 返回局部 State 更新；不得原地修改共享列表或对象。
5. 分支由独立路由函数根据结构化字段决定，不解析自然语言字符串。
6. 重要业务分支必须写中文注释解释“为什么”，不要逐行复述代码。
7. 所有外部结果先经过 Pydantic 校验，再写 State。
8. 不在节点中捕获所有 `Exception` 后继续；只处理已知可恢复错误，未知错误交给统一边界。

## 13. 智能分流 Graph

### 13.1 输入与必填项

智能分流一次只处理一个商品。输入可能来自场景按钮，也可能来自自然语言 ReAct 路由。

必须获得：

- 商品名称。
- 采购用途。
- 预算金额。
- 区域编码。

币种可以为空。区域编码优先读取前端 `pageContext.regionCode`；缺失时与其他缺失字段一起追问。模型只能从用户原始输入提取字段，不得编造缺失值。任何必填字段缺失或预算无法可靠转换为数字时，都必须通过 Form 让用户补充。

### 13.2 主流程

```text
开始
  -> 提取并收集商品名称、采购用途、预算、区域
  -> IOI 采购判断
     -> 是：跳转 IOI 页面并结束
     -> 否：栏目识别
        -> 无栏目：提示采购热线并结束
        -> 一个栏目：直接选中
        -> 多个栏目：等待用户选择一个
  -> 商品推荐 Subgraph
     -> 用户可换一批、追加商品、选择其他采购方式或结束
     -> 搜索无结果时直接进入其他采购方式判断
  -> 栏目允许自行采购？
     -> 否：进入自定义采购
     -> 是：重复自行采购判断
        -> 未重复：等待用户点击“自行采购”并跳转结束
        -> 重复：进入自定义采购
  -> 进入自定义采购时始终查询排队信息
  -> 等待用户点击“自定义采购”
  -> 跳转并结束
```

### 13.3 节点清单与调用约束

| 节点 | 输入 | 行为 | 输出/下一步 |
|---|---|---|---|
| `extract_purchase_fields` | 原始用户文字 | 调用模型提取名称、用途、预算、币种 | 只填可靠字段 |
| `collect_missing_fields` | 当前字段、页面区域 | 缺字段时中断并发 Form | 字段齐全后继续 |
| `judge_ioi` | 名称、用途、预算等正式协议字段 | 调用 IOI Delegate 一次 | `is_ioi` |
| `emit_ioi_navigation` | IOI 结果 | 发 `ioi_purchase` Navigation | 场景完成 |
| `recognize_columns` | 名称、区域、预算、可空币种 | 调栏目 Delegate 一次 | 保存全部候选 |
| `handle_no_column` | 空候选 | 告知未找到栏目并展示配置的采购热线提示 | 场景完成 |
| `choose_column` | 全部候选 | 一个直接选；多个中断单选 | 保存一个栏目 |
| `recommend_products` | 名称、选中栏目 | 运行商品推荐 Subgraph | 商品页或无结果 |
| `choose_procurement_mode` | 栏目自采标识 | 决定是否检查重复自采 | 确定分支 |
| `check_duplicate_self_purchase` | 正式协议字段 | 调重复自采 Delegate 一次 | 是否重复 |
| `offer_self_purchase` | 未重复 | 发自行采购 Action 并等待 | 点击后跳转 |
| `prepare_custom_purchase` | 自采不允许或重复 | 标记进入自定义采购 | 必须进入排队节点 |
| `load_custom_queue` | 当前用户/外部协议字段 | 调 Queue Delegate | 可空数量 |
| `offer_custom_purchase` | 排队结果 | 可选排队文案 + 自定义采购 Action | 点击后跳转 |
| `complete_or_append` | 推荐操作 | 结束或重新收集下一商品 | 相应分支 |

实际文件可以把相邻且短小的纯函数放在同一个场景 `nodes.py`，但节点名称和职责必须与上表一一可追踪。外围接口字段尚未提供时，节点只依赖本文定义的 Delegate 输入模型，禁止猜测 HTTP JSON。

### 13.4 栏目处理

- 栏目识别输入包含商品名称、区域编码、预算金额和币种；币种缺失时传 `null`。
- Delegate 返回栏目名称、品类名称、是否允许自行采购，以及外围协议可提供的稳定栏目 ID。
- 若无稳定栏目 ID，Delegate 在映射后生成仅供本次场景使用的 `option_id`，Graph 不用名称反查。
- 返回一个栏目时直接继续。
- 返回多个栏目时把全部结构化候选保存进 State，并只展示单选。
- 用户提交 `optionId` 后只能从 State 中匹配；禁止再次调用栏目识别 Agent。
- 不允许返回栏目选择的上一步节点；用户若要重新识别，应结束或追加一个新商品流程。

### 13.5 页面跳转与场景结束

- IOI 判断为真后，发送 `ioi_purchase` 导航事件并结束场景。
- 自行采购分支先展示按钮；用户点击后发送 `self_purchase` 导航事件并结束场景。
- 进入自定义采购不等于结束。必须先查询排队信息、展示按钮，用户点击后发送 `custom_purchase` 导航事件，此时才结束。
- 跳转目标固定，所有真实 URL 仅在前端环境配置中维护。

### 13.6 排队信息

只要进入自定义采购，无论原因是“不允许自行采购”还是“重复自行采购”，都必须调用 Queue Delegate。

- 外部接口返回排队数量；数量与排队编号口径一致，当前界面只使用数量。
- 数量大于 0 时原样代入固定文案：

> 前面还有xx单在采购受理中哦～，审批完成后，采购将按顺序为您处理！

- 数量为 `0` 或 `null` 时不展示排队文案。
- Queue 调用超时或失败时记录 Trace，但不阻止展示自定义采购按钮，也不阻止跳转。
- 模型不得生成或改写上述文案。

### 13.7 追加其他商品

用户选择“追加其他商品”后：

1. 清空商品名称、采购用途、预算、币种、栏目和推荐分页状态。
2. 保留页面提供的区域编码；若新 Run 页面仍缺区域，则重新追问。
3. 重新收集商品名称、用途和预算，效果与重新点击智能分流按钮一致。
4. 重新执行 IOI、栏目识别和后续流程。
5. 同一时间仍只处理一个商品，不实现多个商品并行分支。

### 13.8 SmartRoutingState 必需字段

| 字段 | 类型/含义 | 何时清空 |
|---|---|---|
| `scenario_instance_id` | 当前场景实例 ID | 永不在实例内改变 |
| `status` | 场景生命周期枚举 | 只按第 12.6 节变化 |
| `input_source` | `button` 或 `natural_language` | 不清空 |
| `original_user_text` | 本次商品最初原文，可空 | 追加商品时替换 |
| `item_sequence` | 当前场景第几个串行商品，从 1 开始 | 追加时加一 |
| `product_name` | 商品名称 | 追加时清空 |
| `purchase_purpose` | 采购用途 | 追加时清空 |
| `budget_amount` | 使用 `Decimal` 的预算金额 | 追加时清空 |
| `currency` | 可空币种 | 追加时清空 |
| `region_code` | 页面或用户补充的区域 | 页面仍有效时保留 |
| `is_ioi` | 可空布尔；调用后才有值 | 追加时清空 |
| `column_candidates` | 栏目 Agent 的全部已校验候选 | 追加时清空 |
| `selected_column` | 用户选择或唯一栏目 | 追加时清空 |
| `recommendation` | 商品推荐 Subgraph State | 追加时清空 |
| `duplicate_self_purchase` | 可空布尔 | 追加时清空 |
| `entered_custom_purchase` | 是否已进入自定义采购分支 | 追加时清空 |
| `queue_count` | 可空非负整数 | 追加时清空 |
| `navigation_target` | 可空固定跳转目标 | 追加时清空 |
| `wait_request` | 当前等待点 | 每次恢复成功后清空或替换 |
| `recoverable_error` | 可空稳定错误码、能力名和安全文案 | 重试成功后清空 |

State 不保存原始 HTTP 响应、模型客户端、整个知识全集或 Trace 列表。外围原始输入输出进入 Trace；Graph 只保存恢复业务所需的已校验结果。

## 14. 商品推荐 Subgraph

### 14.1 职责边界

商品推荐是主服务内部 Subgraph，不是独立外围 Agent。它只负责：

1. 根据商品名称和已选栏目调用模型拆解有效搜索词。
2. 调用商品搜索接口。
3. 把搜索结果转换为前端商品事件。
4. 管理分页、“换一批”和推荐阶段的用户操作。

商品推荐过程中不使用预算。模型不排序、不过滤最终商品，也不决定权重。

### 14.2 搜索与排序

搜索 Delegate 输入至少包含：

- `search_terms`：模型拆解后的有效搜索词。
- `column_name`：已选栏目名称。
- `user_id`：用于搜索接口计算“本人”和“部门”历史下单量；部门信息由搜索服务按正式协议解析，主服务不自行猜测部门编码。
- `region_code`：页面提供的区域上下文，若搜索正式协议需要区域时一并传入。
- `page`。
- `page_size`，默认 `3`，可由后端配置。

搜索接口负责按以下因素完成加权排序：

- 上架时间。
- 货期。
- 是否电商。
- 历史下单量：所有用户、当前部门、当前本人。
- 直通车。
- 商品是否有效。
- 是否有货。

主服务不得复制一套排序算法，也不得拿到结果后由模型重排。搜索接口返回分页结果、`has_next` 和稳定商品字段；Delegate 负责协议映射和结构校验。

### 14.3 推荐等待点

有商品时发送 `procurement.products`。同一等待点还提供：

- 有下一页时：“换一批”。
- “追加其他商品”。
- “没有满意的商品，请为我推荐另外的采购方式”。
- “结束本次推荐”。

每个商品卡有“加购”按钮，但该按钮只调用前端 `PurchaseFormBridge`：

- 不向后端提交 Action。
- 不恢复或中止当前 Graph。
- 不调用任何 Agent。
- 加购后仍保留换一批、追加商品、其他采购方式和结束按钮。

点击“换一批”时页码加一并再次调用搜索 Delegate。到最后一页后不再展示换一批。搜索接口返回空列表时，先告诉用户没有找到商品；因为此时已经存在选中栏目，所以直接进入“是否允许自行采购”的判断，不再重复栏目识别。

### 14.4 模型拆词约束

- 输入只有商品名称和栏目名称，不传预算。
- 输出是结构化搜索词数组，必须通过 Pydantic 校验。
- 禁止输出排序权重、SQL、搜索表达式脚本或商品结论。
- 结果为空或模型失败时，走统一可重试错误，不凭空使用原句继续生产调用，除非搜索接口正式协议明确支持原句兜底且本文后续更新。
- 同一个商品的换一批复用已经保存的搜索词，不再次调用模型。

### 14.5 RecommendationState 必需字段

| 字段 | 含义 |
|---|---|
| `search_terms` | 已校验的非空搜索词列表 |
| `page` | 当前页，从 1 开始 |
| `page_size` | 创建推荐时读取的配置值，默认 3 |
| `products` | 当前页已映射的商品列表 |
| `has_next` | 搜索接口返回的下一页标识 |
| `result_status` | `not_searched`、`has_products`、`empty` |
| `wait_request` | 推荐操作等待点 |

这里没有预算字段。`page_size` 在同一个商品推荐期间固定，配置部署变化只影响后续新推荐。

## 15. 知识推荐 Graph

### 15.1 固定流程

```text
进入知识推荐
  -> 有查询文字？
     -> 否：通过 Form 收集
     -> 是：继续
  -> Knowledge Delegate 获取全部 key/value
  -> 代码按 key 精确匹配
     -> 找到：原样展示 value
     -> 未找到：展示“未找到相关知识”
  -> 结束
```

### 15.2 精确匹配规则

- 自然语言触发时使用用户本次提交的原始文字作为查询 key；ReAct 不得重写查询内容。
- 按钮触发且没有文字时，通过表单收集查询 key。
- 使用字符串完全相等比较；不做语义、包含、模糊、大小写折叠或标点改写。
- 表单协议可以拒绝空字符串，但匹配前不擅自改写有效内容。
- 多条外部数据出现相同 key 时视为外部协议错误，不任意选择其中一条。
- 命中后的 value 原样作为文字消息返回，禁止模型润色、总结或续写。
- 未命中固定返回“未找到相关知识”。
- 此 Graph 不调用模型，也不实现滑词触发。

### 15.3 进程内缓存

知识数据变化频率低，使用进程内 TTL 缓存：

- TTL 默认 10 分钟，可配置。
- 缓存内容是通过 Delegate 校验后的完整 key/value 集合。
- TTL 内直接读取缓存；过期后第一次请求负责刷新，同进程其他请求等待同一个刷新结果，避免击穿。
- 刷新失败且存在旧缓存时继续使用旧缓存，并记录 `stale_cache_used=true`。
- 刷新失败且从未成功缓存时，向用户返回明确的知识服务暂不可用错误。
- 多进程或多虚拟机各有自己的缓存，允许短时间不一致。
- 首版不为此引入 Redis，不提供手工清缓存接口。

### 15.4 KnowledgeState 必需字段

| 字段 | 含义 |
|---|---|
| `scenario_instance_id` | 当前知识场景实例 ID |
| `status` | 场景生命周期状态 |
| `input_source` | 按钮或自然语言 |
| `query_text` | 用户原始查询 key |
| `match_found` | 可空布尔；完成匹配后赋值 |
| `matched_value` | 命中时的原始 value，可空 |
| `cache_source` | `fresh`、`cached` 或 `stale`，仅用于 Trace/诊断 |
| `wait_request` | 缺 query 时的表单等待点 |
| `recoverable_error` | 首次加载失败时的稳定错误 |

不把完整知识 key/value 集合写入 Checkpoint；它只存在于 `CachedKnowledgeDelegate` 的进程内缓存中。

## 16. Delegate 设计

### 16.1 为什么需要 Delegate

Delegate 是主服务与一个具体外围能力之间的适配边界。不同 Delegate 代表不同能力，不代表“同一种能力的多个供应商”。它负责把主服务稳定的数据模型映射成未来真实接口协议，并把外部响应映射回来。

业务 Graph 只认识 Delegate 接口，不认识 URL、请求头、厂商字段、SSE chunk 或数据库 SQL。外围协议变化时只修改对应 Delegate 及其契约测试。

### 16.2 当前 Delegate 清单

| Delegate | 能力 | 当前调用方 | 是否允许流式展示 |
|---|---|---|---|
| `ModelDelegate` | OpenAI 兼容模型调用 | ReAct、字段提取、搜索词、记忆更新 | 按模型任务配置 |
| `IOIProcurementDelegate` | 判断是否属于 IOI 采购 | 智能分流 | 默认否，可配置 |
| `ColumnRecognitionDelegate` | 返回全部栏目候选 | 智能分流 | 默认否，可配置 |
| `DuplicateSelfPurchaseDelegate` | 判断是否重复自行采购 | 智能分流 | 默认否，可配置 |
| `ProductSearchDelegate` | 分页搜索并完成排序 | 商品推荐 Subgraph | 否 |
| `KnowledgeDelegate` | 获取全部知识 key/value | 知识推荐 | 否 |
| `QueueDelegate` | 获取自定义采购排队数量 | 智能分流 | 否 |
| `DatabaseDelegate` | 会话、Run、Action、记忆和租约的数据库能力 | 应用内部模块 | 否 |
| `TraceDelegate` | 批量保存 Trace span 的数据库能力，属于 Database Delegate 家族 | Trace 收集器 | 否 |
| `CheckpointDelegate` | 向 LangGraph 提供 OpenGauss Checkpointer | Graph 运行器 | 否 |

未来每增加一个外围 Agent 能力，就增加一个清楚命名的 Delegate 接口和实现文件。不得创建一个通过 `agent_name` 分发所有能力的万能 Agent 分发对象。

### 16.3 输入输出必须是明确模型

每个 Delegate 方法都使用独立的 Pydantic 输入和输出模型。含义是：调用方不能随手传任意字典，外部返回也不能未经检查进入 Graph。

示意：

```python
class ColumnRecognitionInput(BaseModel):
    product_name: str
    region_code: str
    budget_amount: Decimal
    currency: str | None = None


class ColumnCandidate(BaseModel):
    option_id: str
    column_name: str
    category_name: str
    self_purchase_allowed: bool


class ColumnRecognitionResult(BaseModel):
    candidates: list[ColumnCandidate]


class ColumnRecognitionDelegate(Protocol):
    async def recognize(
        self,
        request: ColumnRecognitionInput,
        call_context: DelegateCallContext,
    ) -> ColumnRecognitionResult: ...
```

`DelegateCallContext` 只包含调用治理信息，例如 `trace_id`、父 span、剩余截止时间和尝试次数；不得把整个应用容器放进去。

### 16.4 公共 HTTP 能力

所有 HTTP Delegate 复用一个明确配置的异步 HTTP 客户端工厂，统一处理：

- 连接复用和连接池。
- DNS、连接、读取与总调用超时。
- 允许重试的状态码。
- `trace_id` 等内部关联请求头。
- 凭据注入，但禁止将凭据写入 Trace。
- 响应大小上限、Content-Type 检查和 JSON 解析错误。
- 流连接关闭和客户端取消传播。

公共 HTTP 层只处理传输问题，不理解 IOI、栏目或排队业务字段。每个具体 Delegate 自己完成协议映射。

### 16.5 外围协议尚未提供时的处理

当前所有外围 Agent 和普通服务的正式请求/响应协议尚未提供。开发时必须：

1. 先实现本文规定的稳定 Delegate 接口、Pydantic 模型和 Fake。
2. 为生产 Delegate 创建清楚的文件、配置和未配置错误。
3. 不虚构 URL、请求字段、鉴权方式、错误码或流 chunk 格式。
4. 收到正式协议后，只在对应生产 Delegate 内增加映射。
5. 为每份真实协议增加契约样例和契约测试，再把就绪检查改为可用。

production 启动时若必需 Delegate 连正式协议映射或配置都不存在，必须直接启动失败；配置完整但外部服务暂时不可达时允许进程存活，但 readiness 失败或 Trace 显示调用失败。任何情况都不能偷偷调用 Fake。测试 Fake 只能从 `test_support` 装配。

### 16.6 统一外围 Agent 流

外围 Agent 可以是一次性 JSON，也可以是流式响应。每个流式生产 Delegate 必须把原始协议转换成以下内部事件之一：

| 事件 | 含义 | 是否可改变 Graph State |
|---|---|---|
| `progress` | 可展示的进度阶段 | 否 |
| `text_delta` | 明确允许给用户看的文字增量 | 否 |
| `status` | 调用状态变化 | 否 |
| `final_result` | 完整结构化业务结果 | 校验成功后可以 |
| `error` | 安全错误分类 | 否 |

内部事件至少带 `call_id`、`attempt`、事件顺序和时间。规则如下：

- Delegate 必须明确配置 `expose_stream_to_ui`；默认关闭。
- 只转发外部协议明确标记为用户可见的内容。
- Prompt、模型隐藏推理、凭据、内部调试字段和原始异常永不转发。
- 关键业务判断只能读取完整 `final_result`，并先通过 Pydantic 校验。
- 只有进度或文字、没有合法 `final_result` 的流视为失败。
- 非流式 Agent 直接产生一次 `final_result`，不伪造文字流。
- 记录连接开始、首包、首个文字增量和完整结果时间。

若已展示部分流内容后发生自动重试，每次尝试使用不同 `attempt`。前端按 `call_id + attempt` 分组，把失败尝试标为失败，不把两次文字拼成一段；Graph 仍只接受最终成功尝试的结构化结果。

### 16.7 超时、重试与总截止时间

默认配置：

| 配置 | 默认值 |
|---|---|
| 单次外围 Agent/模型调用上限 | 15 秒 |
| 自动重试 | 最多 1 次 |
| 同一逻辑调用的最大实际尝试数 | 2 次 |
| 整个 Run 总截止时间 | 100 秒 |

只自动重试：

- 网络连接失败。
- 超时。
- 限流。
- HTTP 5xx。

不自动重试：

- 输入校验失败。
- 认证或授权错误。
- 明确业务拒绝。
- 2xx 但结构化结果不符合正式契约，除非该 Delegate 明确把某类临时截断定义为可重试。

每次重试前必须检查 Run 剩余时间。若剩余时间不足以完成一次有意义的调用，立即停止，不为了凑重试次数超过 100 秒。100 秒是保护一次交互不会无限占用资源的总边界，必须通过环境变量配置，而不是写死在节点里。

应用层还必须用同一单调时钟截止点对完整业务分发施加 `asyncio.timeout`。原因是只在
Delegate 前检查无法限制卡住的数据库、框架或纯代码步骤。超时边界只包业务分发；场景
`aborted` 补偿、Run `failed/RUN_DEADLINE_EXCEEDED`、租约释放和 Trace 刷新在边界外继续
完成，避免为了限制耗时反而留下永久 `running` 状态。

对于模型调用，最多仍是两次实际尝试：第一次使用主模型；第一次发生可重试错误时，若配置了备用模型则第二次使用备用模型，否则再次使用主模型。没有配置备用模型时不得构造或调用备用模型。结构化输出校验失败按任务的错误策略处理，但总尝试数不能超过两次。

### 16.8 自动重试仍失败

- 关键节点保持在最后一个成功 Checkpoint，不写入伪造业务结果。
- 本次 Run 发安全错误和一个新的一次性“重试”Action。
- 用户点击后使用新 `runId` 从该 Checkpoint 继续。
- 重试 Action 本身仍受 24 小时、用户归属和一次性消费规则约束。
- Queue Delegate 是明确的非阻塞例外：失败后直接继续自定义采购，不要求用户重试。
- Trace 必须分别记录每次自动尝试和用户触发的新 Run，不能只记录最终错误。

### 16.9 错误类型

Domain 中定义有限且可判断的错误分类，例如：

- `InvalidUserInputError`
- `ActionExpiredError`
- `ConcurrentRunError`
- `ScenarioExpiredError`
- `DelegateTimeoutError`
- `DelegateUnavailableError`
- `DelegateContractError`
- `RunDeadlineExceededError`
- `ConfigurationError`

业务代码按类型决定是否追问、重试或终止。对前端只返回稳定错误码和安全中文提示；原始堆栈保存在服务日志，结构化错误摘要保存在 Trace。

## 17. 模型与 Prompt

### 17.1 当前模型任务

| `task_id` | 用途 | Prompt 文件 | 输出 |
|---|---|---|---|
| `scenario_router` | ReAct 选择 Scenario Tool | `business/prompts/scenario_router.md` | Tool 调用或澄清 |
| `purchase_field_extraction` | 提取商品、用途、预算和币种 | `business/prompts/purchase_field_extraction.md` | 结构化字段 |
| `product_search_terms` | 从商品名称和栏目拆解搜索词 | `business/prompts/product_search_terms.md` | 搜索词数组 |
| `memory_update` | 根据完成的 Turn 生成个人记忆更新 | `business/prompts/memory_update.md` | 结构化记忆补丁 |

每个模型任务只有一个主 Prompt 文件。运行时用户输入、页面上下文、Tool Schema 和长期记忆是该 Prompt 的输入数据，不算第二个 Prompt。不得按业务分支动态选择多个 Prompt 变体。

### 17.2 Prompt 如何引用

`business/prompts/catalog.py` 使用常量把 `task_id` 显式映射到固定文件路径和输出模型。应用启动时统一加载并检查文件存在、非空、编码正确；生产请求不能根据用户输入拼接文件路径。

示意：

```python
PROMPT_FILES = {
    "scenario_router": "scenario_router.md",
    "purchase_field_extraction": "purchase_field_extraction.md",
    "product_search_terms": "product_search_terms.md",
    "memory_update": "memory_update.md",
}
```

调用节点只写：

```python
result = await model_delegate.invoke_structured(
    task_id="product_search_terms",
    input_data=request,
    output_type=SearchTermsResult,
    call_context=context,
)
```

节点不自行读取文件、不写内联长 Prompt，也不直接选择 URL 或模型名。Prompt 中复杂约束必须有中文说明，变量名与 Pydantic 字段保持一致。

### 17.3 Model Task Route 是什么

它只是“某个任务使用哪个模型”的静态配置表，不是另一个 Agent，也不做业务路由。例如：

```text
scenario_router        -> primary: local-chat-model, fallback: 未配置
product_search_terms   -> primary: local-chat-model, fallback: backup-model
```

配置放在后端环境配置中，由 `ModelDelegate` 读取。Graph 只传 `task_id`。这样将来切换模型时不修改业务节点，同时没有配置备用模型的任务不会发起备用调用。

不得给任务、Prompt 或模型路由增加业务版本号。配置改变随部署生效，并按第 12.6 节结束旧活动场景。

### 17.4 OpenAI 兼容实现

首个生产实现必须支持配置：

- OpenAI 兼容 `base_url`。
- `api_key`；本地服务允许配置为空，但代码不得擅自填假密钥。
- 模型名称。
- 连接与调用超时。
- 是否支持结构化输出和流式输出。
- 每个任务可选的备用模型。

优先通过 `langchain-openai` 的兼容客户端接入，并在开发时使用实际锁定版本验证。结构化任务必须以 JSON Schema/Tool Schema 约束输出并再次用 Pydantic 校验；不能用正则从自然语言中截取 JSON。

测试使用确定性 Fake Model：按测试输入返回固定结构化结果，并可模拟超时、无效输出、流式增量和备用模型路径。Fake 不能出现在生产 Composition Root。

### 17.5 ReAct 的可见信息

ReAct 只看到：

- 当前用户原始输入。
- 允许使用的 Scenario Tool 名称、说明和参数 Schema。
- 仅用于非关键表达的个人长期记忆。
- 必要的最近对话上下文。

ReAct 看不到 Atomic Tool、Delegate、数据库结构、凭据和全部内部 State。不得要求或保存模型的隐藏思维链；只记录可见输入、Tool 选择、结构化输出、耗时和普通模型响应。

## 18. OpenGauss 与数据库 Delegate

### 18.1 总体规则

- 所有 SQL、连接池和事务都位于 `delegates/database`。
- Graph、Node、API 和 Trace 收集器只能调用数据库 Delegate 接口。
- 使用 Psycopg 3 异步连接池；池大小通过环境配置。
- 所有迁移使用显式、可审阅 SQL，提供向前和回滚说明。
- 时间统一以 UTC 写入 `TIMESTAMP WITH TIME ZONE`，展示时再转换。
- 业务 JSON 使用 OpenGauss 实际支持并验证过的 JSON/JSONB 类型；若目标版本兼容性不足，Delegate 映射为 TEXT 并集中序列化，业务代码不改变。
- 当前不归档、不删除业务、记忆或 Trace 数据。
- 正式环境禁止内存 Checkpointer 和内存数据库 Fake。

### 18.2 逻辑表

具体 SQL 类型必须在真实 OpenGauss 上验证，逻辑字段不得缺失：

| 表 | 关键字段 | 用途 |
|---|---|---|
| `assistant_threads` | `thread_id` PK、`user_id`、活动场景 ID、创建/更新时间 | 会话归属和当前入口 |
| `scenario_instances` | 场景实例 ID PK、用户、会话、`scenario_id`、状态、开始/结束/过期时间、结束原因 | 一个可跨 Turn 的场景 |
| `assistant_runs` | `run_id` PK、用户、会话、场景实例、`trace_id`、输入类型、状态、起止时间、错误码 | 幂等和每次执行审计 |
| `assistant_messages` | 消息 ID PK、用户、会话、Run、角色、原始内容、可展示元数据、时间 | 恢复对话与记忆来源 |
| `assistant_ui_blocks` | 自增块 ID、用户、会话、已校验的 CUSTOM JSON、创建时间 | 刷新时恢复当前 UI 投影；不直接恢复旧 Action |
| `pending_actions` | `action_id` PK、同组 ID、用户、会话、场景、类型、输入 Schema ID、状态、payload、过期与消费信息 | 一次性按钮/表单 |
| `thread_execution_leases` | `thread_id` PK、占用 `run_id`、租约到期时间 | 同一会话不排队串行 |
| `user_memories` | `user_id` PK、`memory_json`、来源 Run、更新时间、最近错误 | 个人长期记忆 |
| `trace_spans` | `span_id` PK、`trace_id`、父 span、Run、名称、类型、状态、各时间点、输入输出 JSON、错误和属性 | 全链路耗时查询 |
| LangGraph Checkpoint 表 | 由选定 Checkpointer 契约要求的 checkpoint、blob 和 write 字段 | Graph 暂停与恢复 |

ID 建议用不超过 64 字符的 UUID/ULID 字符串，避免依赖 OpenGauss 特定 UUID 扩展。所有 JSON 在写入前使用 Pydantic 可序列化模型生成，不直接保存 Python 对象字符串。

### 18.3 必需索引与约束

至少具备：

- `assistant_threads(user_id, updated_at)`。
- `scenario_instances(thread_id, status)`，并由应用与事务保证每个 thread 最多一个活动场景。
- `scenario_instances(expires_at, status)`。
- `assistant_runs(thread_id, started_at)`、`assistant_runs(trace_id)`；`run_id` 唯一。
- `assistant_messages(thread_id, created_at)`。
- `pending_actions(thread_id, status, expires_at)`；`action_id` 唯一。
- `user_memories(user_id)` 唯一。
- `trace_spans(trace_id, started_at)`、`trace_spans(run_id)`、`trace_spans(name, started_at)`、`trace_spans(status, started_at)`。
- Checkpointer 按 LangGraph 官方接口要求的复合键和顺序索引。

所有外键是否物理创建要在 OpenGauss 压测后决定，但应用层归属校验不能省略。状态字段必须有明确枚举约束或写入校验，不能任意字符串。

### 18.4 Checkpoint 实现

优先验证 LangGraph 官方 PostgreSQL Checkpointer 与目标 OpenGauss 版本的兼容性。兼容时：

1. 在 `CheckpointDelegate` 内持有官方 Checkpointer 和专用连接池配置。
2. 由 `business/bootstrap.py` 把它传给 Graph 的 `compile(checkpointer=...)`。
3. API 和业务节点不得直接引用官方 saver 或连接。
4. 迁移脚本显式纳入其所需表，不允许生产启动时静默改表。

若官方实现不兼容，才允许基于 LangGraph 当前 `BaseCheckpointSaver` 正式接口实现 `OpenGaussCheckpointDelegate`。必须覆盖同步要求之外的异步读取、写入、列表、pending writes 和序列化语义，并通过 LangGraph 暂停/恢复集成测试；禁止只建一张 JSON 表模拟后声称兼容。

没有真实 OpenGauss 环境时，这一项必须标记“未完成生产验证”，不得用 PostgreSQL 或内存通过替代结论。

### 18.5 Run 幂等

`runId` 是全局幂等键。入口按下列顺序执行；其中第 4 步才是唯一写事务：

1. 只读查询 `runId` 并校验用户/会话归属；已存在立即返回，不读取 Action。
2. 若是 Action/Form 输入，只读取得 Action，使用其静态 Pydantic Schema 和已保存候选做
   纯校验；非法值在这里结束，因此不会先消费按钮。
3. 构造 `BeginRunRequest`，但不把第一次 Action 读取结果当作授权凭证。
4. `begin_run` 在一个短事务中再次检查 `runId`、原子取得 thread 租约、重新锁定并校验
   Action、消费当前 Action、使同组 Action 失效，最后插入 Run。
5. 提交事务后才调用模型、Graph 或外围接口。第 2 至 4 步之间若 Action 被其他请求消费，
   最终事务返回 `ACTION_EXPIRED`，不会绕过一次性约束。

相同 `runId` 再次到达时绝不重新执行：

- 无论原 Run 是 `running`、`succeeded`、`failed` 还是 `rejected`，均返回 HTTP 409
  `DUPLICATE_RUN`，并在 `details.runStatus` 提供既有状态、在 `snapshotUrl` 提供恢复地址。
- 已失败或拒绝的业务重试必须使用新 `runId`；只有服务端签发的 Retry Action 才能从
  最后成功 Checkpoint 继续。
- `runId` 被其他用户或 thread 使用：按非法归属拒绝，不泄露原记录。

上述重复和 busy 情况统一按第 10.12 节返回 HTTP 409 JSON。未获得租约的同一 `runId` 再次请求仍返回原 `THREAD_BUSY` 结果，前端如需重新尝试必须生成新 `runId`。不为幂等建设完整 SSE Event Store，也不承诺逐 chunk 重放。

### 18.6 同一 thread 串行但不排队

首版不使用 Redis。为支持未来多个进程，不能只用进程内 `asyncio.Lock`。
`DatabaseDelegate.begin_run()` 在入口短事务中原子抢占租约行：

- 成功：租约绑定当前 `runId`，到期时间至少覆盖 100 秒总截止时间和安全余量。
- 失败：立即返回 HTTP 409 `THREAD_BUSY`，不在内存或数据库排队。
- 正常结束：短事务释放租约。
- 进程崩溃：租约到期后可由新 Run 抢占。
- 旧 Run 必须受总截止时间取消，不能在租约过期后继续改变 State。

同一 `user_id` 的不同 `threadId` 使用不同租约，因此可以并行运行多个智能分流场景。

### 18.7 事务边界

严禁在等待模型、外围 HTTP、用户输入或 SSE 发送期间一直占用数据库事务。正确边界是：

- Run 登记、租约获取、Action 最终校验/消费及同组失效：合并在一个短事务中。
- Action 输入模型与候选集合的预校验是消费前只读操作，不持有跨请求事务。
- 每次 Checkpoint：由 Checkpointer 自己完成短事务。
- 消息、场景状态和记忆更新：各自短事务。
- Trace 批量落库：请求结束后的短事务。

“占着事务”会长期占用连接和行锁，使其他请求等待，并在 5000 在线用户时快速耗尽连接池。Graph 跨 Turn 等待数小时也不需要数据库连接，因为恢复位置已经保存到 Checkpoint。

### 18.8 Action 消费原子性

提交 Action 时，数据库 Delegate 在同一短事务中：

1. 按主键锁定 Action。
2. 校验用户、thread、场景、等待组、状态和过期时间。
3. 把当前 Action 标为已消费并记录 `consumed_by_run_id`。
4. 把同组其他 Action 标为失效。

事务提交后再恢复 Graph。若后续执行失败，最后成功 Checkpoint 仍在，系统签发新的重试 Action；不得把旧 Action 改回未消费状态。

## 19. 个人长期记忆

### 19.1 能力边界

- 记忆严格按 `user_id` 隔离，不按部门共享。
- 使用一个 JSON 对象保存，可包含稳定偏好、常见采购背景和表达习惯。
- 系统自动生成和更新。
- 用户当前无需查看、更正或删除自己的长期记忆。
- 当前全部持久化，不做归档或删除。
- 每次需要使用时读取该用户的完整 JSON；首版不做向量检索或摘要分片。
- 记忆只用于非关键个性化表达和推荐辅助，不能决定 IOI、栏目、自采资格、重复采购、排队数量、知识命中或页面跳转。

### 19.2 异步更新

每个 Turn 的最后一个 AG-UI 响应事件发送后，启动受管理的进程内异步任务：

1. 读取本 Turn 的用户输入、可展示助手输出和当前完整个人记忆。
2. 调用 `memory_update` 模型任务，要求返回结构化 `MemoryPatch`。
3. `DatabaseDelegate` 在短事务中锁定该用户记忆行，把补丁合并到当时最新 JSON。
4. 保存来源 `run_id`、更新时间和 Trace。

模型调用期间不持有事务。使用补丁而不是覆盖整个 JSON，避免同一用户多个 thread 并发完成时彼此覆盖。允许补丁增加、更新或删除已经失效的系统记忆键，但用户端不提供删除操作。

该任务不得阻塞用户响应。失败时保留原记忆、记录错误，并允许后续 Turn 再更新。首版不引入持久任务队列，因此进程在响应后立即崩溃时可能丢失本次记忆更新；这是本精简架构明确接受的限制，不能误报为强一致。

### 19.3 读取与注入

Model Delegate 只对明确允许使用记忆的 `task_id` 注入完整 JSON。Prompt 必须把记忆标为“仅供辅助、可能过期、不得覆盖当前用户输入或外部业务结果”。

知识推荐不调用模型，因此不读取记忆。当前商品搜索词严格只使用商品名称和栏目名称，也不使用记忆。未来若增加个性化推荐，只能影响非关键排序辅助或表达，并需更新本文。

## 20. 全链路耗时与 Trace

### 20.1 记录范围

每个 `POST /api/v1/agent` 在 FastAPI 收到请求时创建 `trace_id` 和根 span。根耗时从收到请求开始，直到最后一个 AG-UI 事件交给 ASGI 响应流为止。

必须记录以下层级：

- HTTP 请求和 SSE Run。
- ReAct 路由。
- Scenario Tool、Scenario Graph 和 Subgraph。
- 每个 LangGraph Node。
- 每次 Model、外围 Agent、普通 Service 和 Database Delegate 调用。
- 每次自动重试，分别使用子 span 和 `attempt`。
- Checkpoint 读写、Action、租约、会话、记忆和 Trace 写入。

父子关系通过 `trace_id`、`span_id` 和 `parent_span_id` 表达。不得只记录一条总耗时。

### 20.2 Span 字段

每个 span 至少保存：

- 标识：`trace_id`、`span_id`、`parent_span_id`、`run_id`、`thread_id`、`user_id`。
- 分类：HTTP、Graph、Node、Model、Agent、Service、Database 或 Memory。
- 名称和目标能力。
- `attempt`、状态和稳定错误码。
- `started_at`、`finished_at`、`duration_ms`。
- 流式调用的 `first_byte_ms`、`first_text_delta_ms`、`final_result_ms`。
- 输入 JSON、输出 JSON 和扩展属性 JSON。
- 安全错误摘要；原始 Python 堆栈写服务日志，不直接放前端。

当前决策是不对业务输入输出脱敏，完整持久化用户输入、外围结构化结果和实际模型请求/响应，以便排查问题。但必须在 Trace 序列化边界永久排除 API Key、Authorization/Cookie 请求头、数据库口令和其他凭据。外部提供的隐藏推理内容既不展示也不持久化。

### 20.3 收集与落库

一次 Run 内使用请求局部 `TraceCollector` 收集 span，不能使用跨请求的可变全局列表。节点和 Delegate 使用异步上下文管理器自动结束计时，异常路径也必须写失败状态。

业务响应流结束后，`TraceDelegate` 批量写 OpenGauss：

- 100% 保存，不采样。
- 当前不删除、不归档。
- Trace 写失败不得把已经完成的采购业务改成失败，但必须写服务错误日志。
- 为观察 TraceDelegate 自身耗时，可在主批次后单独写一个 `trace_flush` span；不得递归追踪无限写入。
- 客户端断开时仍在响应生成器的 `finally` 中结束根 span并尝试落库。

### 20.4 直接 SQL 查询示例

本次不建设监控页面和监控查询 API。运维通过只读数据库账号查询，例如：

```sql
-- 查看一次 Run 的完整调用顺序
SELECT name, span_kind, attempt, status, duration_ms,
       first_byte_ms, first_text_delta_ms, started_at
FROM trace_spans
WHERE trace_id = :trace_id
ORDER BY started_at, span_id;

-- 最近一小时各外围能力的调用量、平均和最大耗时
SELECT target, COUNT(*) AS calls,
       AVG(duration_ms) AS avg_ms,
       MAX(duration_ms) AS max_ms
FROM trace_spans
WHERE span_kind IN ('MODEL', 'AGENT', 'SERVICE')
  AND started_at >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
GROUP BY target
ORDER BY avg_ms DESC;

-- 查看失败与重试
SELECT trace_id, run_id, target, attempt, error_code, started_at
FROM trace_spans
WHERE status = 'ERROR' OR attempt > 1
ORDER BY started_at DESC;
```

SQL 参数语法和时间函数需按最终 OpenGauss 客户端验证；应用生产代码始终使用参数绑定，禁止字符串拼接。

## 21. Vue 3 前端设计

### 21.1 前端职责

前端是正式产品界面，不是仅供截图的静态 Demo。它必须直接调用本项目真实 FastAPI/LangGraph 后端，并负责：

- 创建或恢复当前 `threadId`。
- 生成每次请求唯一的 `runId`。
- 用 AG-UI 协议适配器发起 POST + SSE，并处理标准事件。
- 用 Zod 校验采购 `CUSTOM` 事件，再渲染对应组件。
- 提交表单和一次性 Action。
- 通过 `PurchaseFormBridge` 完成前端加购。
- 把固定导航目标映射为部署环境 URL。
- 展示断线、并发冲突、场景过期和可重试错误。

前端不得决定 IOI、栏目、自采、重复采购或排队业务分支，也不得解释外围 Agent 原始协议。

### 21.2 代码模块

建议按以下文件职责实现，名称可因最终 AG-UI SDK API 做小幅调整，但边界不能合并成单个大组件：

```text
frontend/src/
├── App.vue                             # 顶层页面组合，不写协议解析
├── main.ts                             # Vue 和 Ant Design Vue 装配
├── agui/
│   ├── client.ts                       # POST + SSE 的 AG-UI 协议适配器
│   ├── eventReducer.ts                 # 标准事件与已校验采购事件归并
│   ├── procurementEvents.ts            # CUSTOM 事件 TypeScript 类型
│   └── runController.ts                # runId、取消、忙状态和错误映射
├── assistant/
│   ├── AssistantPage.vue               # 助手页面主体
│   ├── useSession.ts                   # 当前 thread、Run 和 UI 快照状态
│   ├── SceneEntrances.vue              # 智能分流/知识推荐按钮
│   ├── MessageList.vue                 # 用户与助手消息
│   ├── DynamicForm.vue                 # 只渲染允许字段类型
│   ├── OptionSelector.vue              # 栏目单选
│   ├── ActionBar.vue                   # 后端一次性操作
│   └── AgentStreamBlock.vue            # 允许展示的外围流进度
├── procurement/
│   ├── ProductList.vue                 # 商品列表和加购
│   ├── QueueNotice.vue                 # 固定排队提示
│   ├── PurchaseFormBridge.ts             # 加购接口
│   ├── LocalPurchaseFormBridge.ts        # 本地 Demo 申购单实现
│   └── HostPurchaseFormBridge.ts         # 公司页面接入实现边界
├── config/
│   ├── env.ts                          # 构建期环境变量校验
│   └── navigation.ts                   # 三个固定目标到 URL 的映射
└── schemas/
    ├── agui.ts                         # 使用 SDK 类型外的入口校验
    └── procurementEvents.ts            # 每种 CUSTOM payload 的 Zod Schema
```

不得把所有事件处理、页面状态和业务组件放入 `App.vue`。TypeScript 必须开启严格模式，业务事件禁止使用 `any`。

### 21.3 AG-UI 事件处理

处理顺序：

1. `agui/client.ts` 解析标准 SSE 事件，并用 Zod 校验 AG-UI 事件结构。
2. `CUSTOM` 事件按 `name` 找到固定 Zod Schema。
3. 校验 `schema`、`threadId`、`runId`、`eventId`、`sequence` 和 payload。
4. `eventReducer` 以不可变方式更新界面状态。
5. 组件只读取已经校验的界面模型。

规则：

- 同一 Run 的 `sequence` 必须严格递增；重复 `eventId` 忽略并记录浏览器诊断日志。
- `threadId` 或 `runId` 与当前请求不一致的事件不得应用。
- 未知采购 `name` 或不支持的 `schema` 不渲染，显示一次安全的“界面协议不兼容”错误。
- payload 中的字符串按普通文本渲染，禁止使用 `v-html`。
- `RUN_FINISHED` 只表示本次 Run 结束，不自动表示整个场景结束；场景状态以 `procurement.scene` 为准。
- 页面刷新后先获取 snapshot，再允许提交与快照等待点匹配的 Action。

### 21.4 场景入口和会话

- 没有活动场景时显示“智能分流”和“知识推荐”两个入口按钮。
- 点击按钮发送 `scenario_trigger`，不发送伪造自然语言。
- 活动场景处于 `running` 或 `waiting` 时隐藏所有场景入口按钮。
- 场景完成、中止或过期后重新显示入口。
- 支持“新会话”：生成新 `threadId` 并清空当前页面状态，不删除旧会话数据库数据。
- 不实现历史会话列表。

当前 tab 的 `threadId` 保存到 `sessionStorage`，页面刷新继续使用；新 tab 默认创建独立 thread。任何来自 URL 或浏览器存储的 thread 仍须由后端按 `user_id` 校验归属。

### 21.5 Action 与表单

- Action 按钮提交自身 `actionId`；点击后立即进入 pending 状态，防止双击。
- 后端成功响应或明确失败后再更新按钮状态。
- 同组任一 Action 被成功消费后，前端立即禁用同组全部按钮。
- Form 只渲染 `text`、`number` 和 `select`；必填、长度、最小/最大值由协议驱动。
- 前端校验用于及时提示，后端 Pydantic 校验仍是最终依据。
- 不允许后端下发组件名、JavaScript、任意校验表达式或任意 API 地址。

### 21.6 PurchaseFormBridge

统一接口表达为：

```typescript
export interface PurchaseFormBridge {
  addProduct(product: PurchasableProduct): Promise<AddProductResult>;
}
```

- `LocalPurchaseFormBridge` 在轻量版独立页面中维护本地申购单，用于完整 Demo 和 E2E。
- `HostPurchaseFormBridge` 是接入公司既有申购单页面的边界；正式宿主协议提供后再实现映射。
- `ProductList` 只依赖接口，不判断当前是哪种实现。
- 点击加购只调用 Bridge，不向 Agent 后端发送请求，不结束或恢复 Graph。
- 加购成功显示明确反馈；失败保留商品和所有推荐操作，允许用户再次点击。
- 禁止将测试 Bridge 打入生产部署，生产模式未配置真实宿主且又不允许本地申购单时必须明确报错。

### 21.7 页面跳转

前端只接受三个固定目标：

```text
ioi_purchase
self_purchase
custom_purchase
```

`config/navigation.ts` 从经过校验的构建环境变量建立目标到 URL 的映射。事件中的 `params` 只能映射成预定义允许参数；禁止把后端字符串直接作为 `window.location`。

- IOI 分支收到 Navigation 后按产品要求直接跳转。
- 自行采购和自定义采购只有在用户已点击对应后端 Action、随后收到 Navigation 事件时跳转。
- 找不到目标配置时不跳转，显示配置错误并保留当前页面。

### 21.8 Chrome 与无障碍基本要求

正式验收只覆盖桌面版 Chrome。仍必须做到：

- 所有操作可用键盘聚焦和触发。
- 表单 label 与错误提示关联。
- 流式更新使用适当的 `aria-live`，避免每个 token 都打断读屏。
- Action pending、禁用和加载状态可见。
- Ant Design Vue 主题使用 `a-config-provider` 的 token 管理，不散落大量行内色值。
- 长内容、商品名称和错误文案不能遮挡主要按钮。

## 22. 配置、缓存与容量边界

### 22.1 后端配置

所有环境变量由 `business/config/settings.py` 中的 `AppSettings` 在启动时一次性读取和校验；
它再把 Core 与 Business 真正需要的字段分别转换成小型配置对象。至少包含：

| 配置 | 默认/要求 |
|---|---|
| `APP_ENV` | `local`、`test` 或 `production` |
| `DATABASE_DSN` | production 必填，日志中隐藏凭据 |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | 按部署容量显式配置 |
| `HTTP_MAX_CONNECTIONS` / `HTTP_MAX_KEEPALIVE_CONNECTIONS` | 公共外围 HTTP 连接池上限，默认 `500`/`100` |
| `HTTP_MAX_RESPONSE_BYTES` | 外围普通/流响应大小上限，默认 `10 MiB` |
| `RUN_DEADLINE_SECONDS` | 默认 `100` |
| `DELEGATE_ATTEMPT_TIMEOUT_SECONDS` | 默认 `15` |
| `DELEGATE_MAX_ATTEMPTS` | 固定默认 `2`，代表首次加一次重试 |
| `THREAD_LEASE_GRACE_SECONDS` | 默认 `30` |
| `CHECKPOINT_TTL_HOURS` | 默认 `24` |
| `KNOWLEDGE_CACHE_TTL_SECONDS` | 默认 `600` |
| `PRODUCT_PAGE_SIZE` | 默认 `3` |
| `PROCUREMENT_HOTLINE_TEXT` | production 必填的无栏目引导文案 |
| `MODEL_BASE_URL` / `MODEL_API_KEY` / `MODEL_NAME` | 主 OpenAI 兼容模型配置 |
| 备用模型配置 | 全部可空；为空时不得调用 |
| 每个外围 Delegate URL/凭据/流展示开关 | 正式协议提供后逐项增加 |
| CORS 允许来源 | production 必须显式列出 |

超时、重试、TTL 和分页值必须验证合理范围。代码不得在多个模块重复读取环境变量；只有 Composition Root 接收 Settings 并把具体值传给对象。

### 22.2 前端配置

至少验证：

- 后端 API 基础地址。
- 三个固定导航目标 URL。
- 宿主页面模式或本地申购单模式。
- 开发环境的默认 `user_id`；production 必须由公司页面上下文提供。

Vite 暴露到浏览器的环境变量不能包含 API Key、数据库 DSN 或外围服务凭据。

### 22.3 首版缓存

首版只有知识全集使用进程内 TTL 缓存。以下内容不做业务缓存：

- Checkpoint、会话、Action 和长期记忆。
- IOI、栏目、重复自采和排队结果。
- 商品搜索页。
- 模型结果。

HTTP 客户端连接池和数据库连接池属于连接复用，不是业务缓存。不得为了“可能更快”自行加入隐藏字典缓存。

### 22.4 用户规模与并发含义

目标背景是约 20 万用户、峰值约 5000 个同时在线用户，未来按峰值 500 请求/秒评估。这里的“同时在线”不等于同时占用数据库连接：

- 用户在页面阅读或等待输入时，Graph 已 Checkpoint，不持有 Python Task、SSE、数据库事务或连接。
- SSE 只在一次 Run 执行期间存在，默认最长受 100 秒截止时间控制。
- 外部 Agent 慢时占用异步任务和 HTTP 连接，但不应占用数据库事务。
- 数据库连接池大小根据真实并发 SQL 数量设置，不能机械设置成 5000。

首次试运行不以 500 请求/秒作为上线门槛，但代码必须无服务端内存会话依赖，允许启动多个后端进程。达到目标规模前必须进行真实 OpenGauss、模型和外围服务容量测试。

### 22.5 过载保护

- ASGI、HTTPX 和数据库池都设置明确上限。
- 同 thread 并发立即 409，不排队。
- 服务器达到全局并发保护上限时快速返回 503/429 和 `Retry-After`，不能无限堆积协程。
- 每个慢外围能力可配置独立并发上限；等待许可也计入 100 秒总截止时间。
- 请求体、消息长度、流事件大小和外围响应大小必须设上限，具体值在正式协议到齐后通过测试锁定。
- Nginx 对 SSE 关闭代理缓冲，读取超时必须大于后端总截止时间和收尾余量。

未来若多实例知识缓存一致性、分布式限流或热点读取成为实际问题，再评估 Redis。首版代码不得强依赖 Redis 才能正确执行。

## 23. 安全与数据边界

### 23.1 当前身份风险

当前 `X-User-ID` 由前端直接传入且不验签，这是已确认的临时决策，不等同于安全认证。系统部署在公司内网也不能省略数据归属校验：

- 每个 thread、场景、Run、Action、消息和记忆读取都附带 `user_id` 条件。
- 不存在或不属于当前用户统一返回 404/安全错误，避免枚举。
- user ID 格式和长度受限，不能写入 SQL、日志格式字符串或文件路径。
- 上线到更广网络或处理真实敏感采购数据前，必须接入可信身份头或网关认证。

### 23.2 模型和 Prompt 注入边界

- 顶层 ReAct 只能调用静态 Scenario Tool。
- 关键业务 Graph 的边由代码和结构化字段决定，用户文字不能直接选择节点名。
- 外围返回文字一律视为数据，不能作为新的系统指令执行。
- 模型不能生成 URL、SQL、Delegate 名称、任意 Tool import 或前端组件。
- 模型结构化输出必须经过 Pydantic 校验和业务枚举检查。
- 不记录、不请求、不展示隐藏思维链。

### 23.3 HTTP 与浏览器边界

- Delegate URL 只来自服务端配置，用户输入不能成为请求主机或协议，防止 SSRF。
- CORS 只允许明确公司页面来源。
- 生产环境要求 HTTPS 或由可信内网反向代理终止 TLS。
- SSE 响应设置禁止缓存，Nginx 不缓冲。
- 前端不渲染任意 HTML，不执行事件中的脚本，不跳转任意 URL。
- 依赖安装使用锁文件和 frozen 模式，发布前执行依赖漏洞扫描并记录结果。

### 23.4 凭据与持久化数据

- 凭据由虚拟机环境文件、systemd credential 机制或公司现有安全配置提供，不提交仓库。
- 当前不建设独立密钥管理服务。
- 服务日志和 Trace 永远过滤 Authorization、Cookie、API Key、数据库密码和完整 DSN。
- 已确认当前业务输入输出不脱敏并长期保存；这意味着 OpenGauss 访问权限、备份权限和只读查询账号必须最小化。
- 用户当前没有记忆查看、更正或删除能力；若未来合规要求改变，必须补充对应接口和数据生命周期设计。

## 24. 部署设计

### 24.1 共同部署原则

- 公司内网虚拟机部署，不依赖 Kubernetes。
- OpenGauss 作为已有或独立部署的数据服务，不嵌入后端进程。
- Nginx 作为前端静态站点和后端/SSE 反向代理入口。
- 不部署 OpenTelemetry、Prometheus、Grafana 或独立告警系统。
- 后端进程必须无本地会话状态；本地知识缓存允许各进程独立。
- 生产配置和 Fake 配置使用不同 Composition Root/启动入口，不能用一个开关在运行中切换。

### 24.2 虚拟机原生部署

交付内容：

- Python 3.12 虚拟环境，按 `uv.lock` frozen 安装。
- Node 24 只用于构建；运行时由 Nginx 提供 `frontend/dist`。
- systemd 启动 Uvicorn，明确工作目录、环境文件、用户、重启策略和优雅停止时间。
- Nginx 路由 `/` 到静态前端，`/api/` 到 FastAPI，并为 SSE 关闭缓冲与缓存。
- 独立迁移命令和部署前场景过期命令。

推荐部署顺序：

1. 备份配置并验证新锁文件。
2. 构建后端环境和前端静态文件到新发布目录。
3. 运行数据库迁移及校验。
4. 调用内部管理脚本，通过 Database Delegate 把活动场景标为 `expired`；不直接在 shell 拼 SQL。
5. 原子切换发布目录并重启后端。
6. 验证 live、ready、AG-UI 冒烟和前端静态资源。
7. 失败时按迁移兼容性说明回滚程序；不得恢复已过期旧场景。

### 24.3 Docker 部署

- 后端镜像使用 Python 3.12 固定基础镜像和多阶段构建。
- 前端镜像使用 Node 24 构建、Nginx 运行。
- 最终镜像不包含 `tests`、`test_support`、开发依赖、npm 缓存或源码凭据。
- Compose 文件装配前端、后端和可选统一 Nginx；OpenGauss 默认通过外部地址连接，不在 Compose 中假装生产数据库。
- 容器使用非 root 用户、只读应用文件和可写临时目录。
- 环境变量或只读 secret 文件在运行时注入。
- 场景过期和迁移作为显式一次性部署步骤，不在每个并发启动实例中自动竞争执行。

### 24.4 健康检查

`/health/live` 只证明进程事件循环可以响应，不调用所有外围服务。

`/health/ready` 至少验证：

- 配置完整且模式合法。
- OpenGauss 可连接，必要迁移和 Checkpoint 表存在。
- 生产 Composition Root 没有 Fake。
- 必需模型与 Delegate 的协议配置已提供。
- Prompt 和静态 Tool 目录加载成功。

慢外围服务不应在每次 ready 请求中实际调用；其最近失败由 Trace 查询。ready 响应不得暴露 DSN、URL 凭据或模型密钥。

### 24.5 优雅停止

- 停止接收新请求。
- 给正在执行的 Run 有限时间结束，但不能超过 systemd/Docker 停止上限。
- 取消未完成外围流并释放 HTTP 连接。
- 应用层在成功的 `RUN_FINISHED` 或失败的 `RUN_ERROR` 前完成 Run 终态和租约释放；响应
  生成器 `finally` 再保证根 span 结束、进程容量释放和 Trace 尽力落库。
- 等待受管理的记忆更新任务到设定短上限，超时则取消并记录。
- 关闭 HTTP 和数据库连接池。

## 25. 后端逐文件实施蓝图

### 25.1 接入与协议

```text
backend/src/procurement_assistant/
├── main.py                              # 只调用 business.bootstrap，不创建隐藏全局依赖
├── core/api/
│   ├── app.py                           # create_app 与路由装配
│   ├── dependencies.py                  # 身份和 HTTP 请求上下文
│   ├── errors.py                        # Domain 错误到 HTTP/AG-UI 错误映射
│   ├── agent.py                         # POST /api/v1/agent
│   ├── sessions.py                      # 当前 thread snapshot
│   ├── health.py                        # live/ready
│   └── sse.py                           # AG-UI 事件编码和响应生成器
└── core/protocol/
    ├── run_input.py                     # forwardedProps 的区分输入模型
    ├── events.py                        # 与业务无关的文本、场景等通用内部事件
    ├── emitter.py                       # 通用内部事件到 AG-UI 的单向适配
    └── snapshot.py                      # 只含前端恢复所需字段
```

采购商品、选项、排队信息和页面跳转等业务事件位于
`business/protocol/events.py`，由业务节点创建，再通过 Core 的通用发送器输出。Core 不认识
这些 payload 的采购含义。

`agent.py` 只执行固定接入步骤：校验输入和身份、调用应用层准入、把应用事件交给 SSE，
并在流生成器 `finally` 释放进程容量和刷新 Trace。场景选择、Graph 恢复、Run 终态和租约
释放由 `core/orchestration/application.py` 负责；采购节点不得写在路由文件中。

### 25.2 Core 编排

```text
core/orchestration/
├── application.py                       # Run 准入后分发、总截止时间和统一收尾
├── runtime.py                           # ExecutionContext 与 Delegate 调用治理
├── graph_runner.py                      # invoke/stream、interrupt 和 Checkpoint 协调
├── actions.py                           # WaitRequest、Action 操作和签发定义
├── action_registry.py                   # Business 注入的输入模型静态注册表
├── resume.py                             # 通用 interrupt 恢复值
├── wait_factory.py                      # 通用等待组、Action ID 和 24 小时有效期
├── scenarios.py                          # ScenarioDefinition 和只读 ScenarioRegistry
├── models.py                            # 少量跨场景编排模型
├── router/
│   ├── react_router.py                  # 顶层 ReAct，只使用 Scenario Tool
│   └── scene_switch.py                  # 场景切换候选与确认
```

Core 只放以上通用文件。具体场景、Tool、业务 Action 和业务事件都在 Business：

```text
business/
├── bootstrap.py                         # 唯一装配入口
├── registry/
│   ├── scenarios.py                     # 显式汇总 ScenarioDefinition
│   ├── atomic_tools.py                  # Atomic Tool 显式注册（当前为空）
│   ├── model_tasks.py                   # 业务模型任务 ID
│   └── interactions.py                  # 表单模型和 Action 输入注册
├── interaction/
│   ├── operations.py                    # 业务操作编号
│   ├── action_inputs.py                 # 业务输入模型和栏目候选校验
│   └── wait_factory.py                  # 采购表单、选项和业务按钮
├── tools/
│   ├── start_smart_routing.py           # 智能分流 Scenario Tool
│   └── start_knowledge_recommendation.py # 知识推荐 Scenario Tool
├── scenarios/
│   ├── smart_routing/
│   │   ├── definition.py                # 依赖、说明、Tool 和 Graph 的完整定义
│   │   ├── state.py                     # SmartRoutingState
│   │   ├── nodes.py                     # 采购业务节点
│   │   ├── routes.py                    # 只根据结构化 State 分支
│   │   └── graph.py                     # 显式 add_node/add_edge/compile 构图
│   ├── knowledge/
│   │   ├── definition.py                # 知识场景完整定义
│   │   ├── state.py                     # KnowledgeState
│   │   ├── nodes.py                     # 收集、加载、精确匹配、展示
│   │   └── graph.py                     # 确定性构图
│   └── subgraphs/product_recommendation/ # 业务内部商品搜索子图
```

`graph.py` 必须能从上到下读出完整节点和边。不得用循环读取数据库配置生成 Graph，不得把边隐藏在装饰器副作用中。`nodes.py` 过长时可以按清晰业务阶段拆成多个文件，但不能创建一层只有转发作用的类。

### 25.3 Delegate 与 Prompt

```text
core/delegates/
├── common/
│   ├── call_context.py                  # trace、deadline 和 attempt
│   ├── http_client.py                   # 连接池、超时、凭据和流读取
│   └── stream_events.py                 # 五类内部 Agent 流事件
├── model/
│   ├── interface.py                     # ModelDelegate Protocol
│   └── openai_compatible.py             # LangChain/OpenAI 兼容实现
business/delegates/agents/
│   ├── ioi.py                           # IOI 接口与待映射生产实现
│   ├── column_recognition.py            # 栏目接口与待映射生产实现
│   └── duplicate_self_purchase.py       # 重复自采接口与待映射生产实现
business/delegates/services/
│   ├── product_search.py                # 搜索接口与分页结果
│   ├── knowledge.py                     # 知识全集接口
│   ├── cached_knowledge.py              # 单航班刷新和 10 分钟缓存
│   └── queue.py                         # 排队数量接口
core/delegates/database/
    ├── interface.py                     # 不依赖 Psycopg 的通用 DatabaseDelegate 协议
    ├── connection_types.py              # 全部数据库实现共用的字典行连接池类型
    ├── opengauss.py                     # Run、租约、场景、Action、消息和记忆的短事务 SQL
    ├── trace.py                         # 不依赖驱动的 TraceDelegate 协议
    ├── opengauss_trace.py               # span 批量写入 OpenGauss 的独立实现
    └── checkpoints.py                   # 官方 saver 的 OpenGauss 适配边界

business/prompts/
├── catalog.py                           # Business 任务 ID 到固定文件的只读映射
├── scenario_router.md                   # 一个任务一个 Prompt
├── purchase_field_extraction.md
├── product_search_terms.md
└── memory_update.md
```

`core/api/sessions.py` 只实现“按策略保留最新 UI 块”的通用算法；业务事件名称白名单由
`business/protocol/snapshot.py` 的 `ProcurementSnapshotPolicy` 注入。新增业务事件时，
只需在 Business 策略中决定是否可恢复，不需要修改 Core 会话接口。

`core/delegates/database/opengauss.py` 按“Run 入口事务、Thread/场景/Action、展示内容/记忆、事务内辅助函数”设置
清楚分区。`begin_run` 需要在一个事务中同时处理租约、Action 和 Run，因此当前保留在同一
实现类中，便于从上到下审核原子性；Trace 已拆到独立文件。不得仅为减少行数引入多重
Mixin 或无业务含义的转发类。未来只有在真实 OpenGauss 集成测试覆盖跨模块事务后，才可
继续拆分，并且必须保持 `DatabaseDelegate` 单一边界。业务层只能看到 `begin_run`、
`update_scenario_status`、`merge_memory` 等有业务含义的方法，永远不暴露 `execute(sql)`。

主数据库、Trace 和官方 LangGraph Checkpointer 必须共用
`connection_types.OpenGaussPool`，并在 Composition Root 用 `dict_row` 配置连接池。不能
把 Psycopg 默认 tuple 行连接池用类型断言伪装成字典行连接池；官方 Checkpointer 的接口
和按字段名读取的业务 SQL 都依赖真实字典行配置。

### 25.4 Domain、Trace 和 Shared

```text
business/domain/
└── procurement.py                       # 商品、栏目、预算等纯数据模型

core/domain/
├── identifiers.py                       # 强约束 ID 值模型
├── lifecycle.py                         # 场景/Run/Action 状态枚举
└── errors.py                            # 与框架无关的错误

core/observability/
├── models.py                            # Span 类型、状态与完整耗时字段
├── collector.py                         # 请求局部收集器、父子上下文和 async 计时器
├── flusher.py                           # Trace 尽力而为批量落库及 flush 耗时
└── checkpointer.py                      # 给官方 Saver 增加 Checkpoint 数据库 span

core/shared/
├── clock.py                             # 可测试 UTC 时钟
└── ids.py                               # UUID/ULID 生成
```

如果某个 shared 文件没有三个以上真实调用方，就把它留在最接近的模块。禁止建立 `utils.py`、`helpers.py` 或 `common.py` 万能文件。

### 25.5 Composition Root 的装配顺序

`business/bootstrap.py` 必须按显式顺序创建：

1. 校验 Settings。
2. 创建时钟、ID 生成器和连接池。
3. 创建 Database/Checkpoint Delegate。
4. 创建公共 HTTP 客户端。
5. 创建 Model、Agent 和 Service Delegate。
6. 创建 Prompt Catalog、Scenario Registry、Atomic Tool Registry 和交互 Registry。
7. 用构造函数把所需 Delegate 传入 Node/Tool。
8. 构建并编译 Subgraph，再构建两个 Scenario Graph。
9. 创建 ReAct 路由器、Graph Runner、协议发送器和 FastAPI。
10. 注册启动和关闭资源生命周期。

不得在 import 模块时打开连接、读取数据库或创建后台任务。测试 Composition Root 使用 `test_support` 的 Fake 实现，但执行同一套真实 Graph、API 和前端协议。

## 26. 测试与质量验收

### 26.1 测试代码严格分离

- `backend/src`、`frontend/src` 不得包含 Fake、fixture、Mock 响应或仅测试入口。
- 后端测试只在 `tests`，可控 Fake 只在 `test_support`。
- 前端 E2E fixture 放 `tests/e2e` 或 `test_support/fixtures`，不得放 `frontend/src`。
- 生产代码不能 import `tests` 或 `test_support`。
- 生产 Docker 构建必须用文件清单或 `.dockerignore` 排除二者，并通过镜像内容检查。
- production Composition Root 的类型和启动检查必须证明没有 Fake 实例。
- 测试不能 monkey patch 全局依赖来绕过显式装配。

本项目不要求为每个 getter 或纯数据类编写细粒度单元测试，也不设虚假的全局行覆盖率门槛。下面列出的契约、集成、E2E 和并发路径一个都不能少。

### 26.2 静态质量门禁

每次交付必须全部通过：

- Ruff 格式和规则检查。
- mypy 严格检查；若第三方库缺类型，只能在最小适配文件局部豁免并写原因。
- ESLint、Prettier 检查。
- TypeScript `strict` 编译和 Vite production build。
- 后端、前端依赖锁文件一致性和 frozen 安装验证。
- 禁止 import 规则检查。
- 生产镜像中无测试代码、源码密钥和开发依赖的检查。

禁止用整文件 `# type: ignore`、大量 `Any`、关闭 TypeScript strict 或跳过 lint 来通过门禁。复杂代码必须有解释设计原因的中文注释；普通赋值不需要噪声注释。

代码可读性和中文注释是硬性验收项，而不是建议：

- 模块、公开类、公开函数、Graph 节点、Delegate 接口和关键 Pydantic 模型必须有中文 Docstring，说明职责、输入输出、边界和失败方式。
- Graph 分支、Interrupt/恢复、幂等、事务、租约、重试、超时、流式映射、记忆合并和安全过滤等非直观逻辑，必须在相邻位置写充分且详细的中文注释，重点解释“为什么这样做”和“不这样做会有什么问题”。
- 外围协议映射必须逐段注释外部字段与内部字段的对应关系；正式协议尚未提供时必须明确标注阻塞原因，不能留下含糊 `TODO`。
- 函数和文件保持单一职责；出现长函数、深层嵌套、万能参数字典或无法从名称判断用途的变量，视为可读性不合格。
- 注释必须与代码同步更新，不得保留失效、复制粘贴或只是逐字复述赋值语句的注释。
- 中文业务术语在代码、注释、事件协议和本文中保持一致；首次使用不可避免的英文框架术语时，在 Docstring 中用中文解释。
- 代码评审必须逐文件检查上述要求；即使功能测试全部通过，可读性或中文注释不合格也不得验收。

### 26.3 契约测试

必须覆盖：

1. AG-UI 标准 Run、文字流、错误和结束事件能被前端 Client 消费。
2. 每一种采购 `CUSTOM` 事件同时通过后端 Pydantic 与前端 Zod；缺字段、错类型、未知 schema 均拒绝。
3. `RunAgentInput` 三类采购输入互斥，非法组合拒绝。
4. Navigation 只接受三个固定目标，任意 URL 拒绝。
5. Form 只接受三类字段，未知组件和脚本字段拒绝。
6. 每个 Delegate 的 Fake 与接口模型完全一致。
7. 拿到真实外围协议后，每个生产 Delegate 使用供应方固定样例验证请求映射、成功、业务错误、超时和畸形响应。
8. 流式 Delegate 验证五类内部事件、final 校验、隐藏字段过滤、首包/首字计时和重试 attempt 分组。
9. OpenAI 兼容模型验证普通、结构化、Tool 调用、流式、超时、主模型重试与可选备用模型。
10. OpenGauss Checkpointer 使用目标数据库验证 pending writes、interrupt、resume、并发和序列化。

### 26.4 智能分流集成测试矩阵

使用真实编译 LangGraph 和 Fake Delegate，至少覆盖：

1. 按钮准确进入智能分流，不调用 ReAct。
2. 自然语言由 ReAct 只选择智能分流 Scenario Tool。
3. 商品、用途、预算、区域分别缺失及多项缺失时正确追问。
4. 页面区域存在时不追问；区域缺失后用户补充可继续；币种为空仍调用栏目。
5. IOI 为真：不调用栏目和搜索，发送 IOI 导航并完成。
6. IOI 为假、栏目为空：展示采购热线，不调用推荐并完成。
7. 单栏目直接继续。
8. 多栏目只调用栏目 Agent 一次；用户选一个后从 Checkpoint 继续，Delegate 调用次数仍为一次。
9. 多栏目提交未知/其他用户/过期 `optionId` 均拒绝，不改变 State。
10. 商品拆词不包含预算；换一批不再次拆词。
11. 默认每批正好最多三件，下一页正确变化，最后一页不展示换一批。
12. 搜索结果顺序原样展示，不由模型或主服务重排。
13. 加购不产生后端请求、不结束 Graph，其他推荐按钮仍有效。
14. 追加商品清空商品相关 State，重新收集并重新执行 IOI 和栏目。
15. 用户主动结束推荐后场景完成，旧 Action 失效。
16. 有栏目但搜索为空：提示无商品并进入采购方式判断，不重复识别栏目。
17. 栏目允许自采且未重复：展示自行采购按钮；点击后导航并完成。
18. 栏目允许自采但重复：进入自定义采购并调用 Queue。
19. 栏目不允许自采：不调用重复探针，进入自定义采购并调用 Queue。
20. Queue 数量大于 0：文案逐字一致且数量正确。
21. Queue 为 0/null：不展示排队文案。
22. Queue 超时/失败：记录失败但仍展示自定义采购按钮。
23. 展示排队时场景仍为 waiting；点击自定义采购、收到导航后才完成。
24. 用户确认切换场景：原场景 aborted、旧 Action 失效、新场景开始。
25. 用户取消切换：原场景等待点和候选完整恢复。

每条测试必须同时断言 Delegate 调用次数、最终 State、关键事件和场景状态，不能只断言 HTTP 200。

### 26.5 知识与缓存集成测试

必须覆盖：

- 按钮进入时缺查询值会显示 Form。
- 自然语言原文作为 key，不经模型改写。
- 完全相等命中并逐字返回 value。
- 大小写、标点、空格或子串不同不命中。
- 未命中固定返回“未找到相关知识”。
- 重复 key 被判定为契约错误。
- TTL 内只调用一次外部接口。
- 并发首次加载只有一个刷新调用。
- TTL 过期正常刷新。
- 刷新失败有旧缓存时返回旧值并记录 stale。
- 首次加载失败时返回明确服务不可用。
- 全路径均不调用模型。

### 26.6 恢复、并发、错误和记忆集成测试

必须覆盖：

- 每种 Form/Options/Actions interrupt 跨新 Run 恢复。
- 服务进程重建后通过同一 Checkpointer 恢复最后成功状态。
- 24 小时边界前可恢复、边界后 expired；记录保留不删除。
- 部署过期命令使全部活动场景不可恢复，且没有 Graph 版本字段。
- Action 一次消费、同组失效、用户/thread/场景归属和过期校验。
- 非法表单值和不存在于已保存候选中的栏目值在消费前拒绝，修正后原 Action 仍可使用。
- 相同 `runId` 并发或重复提交只执行一次。
- 相同 `runId` 的重放即使携带损坏 Action 正文，也优先返回 `DUPLICATE_RUN`。
- 同一 thread 并发只有一个获取租约，其余立即拒绝且不排队。
- 不同 thread 可并行且 State、Action、Trace 不串线。
- 租约随正常结束释放、进程失败后按到期恢复。
- 外围调用可重试错误最多两次；非重试错误只调用一次。
- 总截止时间生效，重试前检查剩余时间。
- 无备用模型时从不调用备用；配置后只按既定第二次尝试使用。
- 自动尝试都失败后从最后 Checkpoint 签发用户重试 Action。
- 不可重试 Delegate 错误只调用一次，并把场景终止为 `aborted`、Run 终止为 `failed`。
- 客户端断线后 Run 写入 `CLIENT_DISCONNECTED`，活动场景 `aborted`，租约和 Action 均失效。
- 部署过期命令把活动场景改为 `expired`、清活动指针，并使旧 Action 无法提交。
- 记忆更新在最后事件之后执行且不增加用户响应耗时。
- 同一用户并行 thread 的记忆补丁合并不互相覆盖。
- 记忆失败不影响业务，且关键业务节点不读取记忆决定分支。
- Trace 有完整父子 span、两次尝试、首包/首字/总耗时和输入输出。

### 26.7 Chrome E2E

Playwright 只使用桌面 Chrome 项目，启动真实 FastAPI、真实编译 Graph、正式 Vue 3 构建和测试专用 Fake Delegate。至少自动完成：

1. 自然语言进入智能分流，补表单、多栏目选择、展示商品、加购、换一批、进入自定义采购、展示排队、点击跳转。
2. IOI 直接跳转。
3. 未重复自采点击跳转。
4. 知识命中原样展示和未命中。
5. 页面刷新恢复 Options、Form、商品操作和排队等待点。
6. 场景切换确认与取消。
7. 断流、外围失败、用户重试和场景过期界面。
8. 新会话生成新 thread，旧数据不出现在新会话。
9. 键盘操作、加载/禁用状态和基本可访问性。

E2E 禁止拦截后端接口后返回静态页面数据；必须让请求进入真实后端 Graph。外围边界由 Fake Delegate 控制是允许且必要的。

### 26.8 并发冒烟与容量测试

当前交付至少使用 k6 验证：

- 100 个不同 thread 并发执行 Fake 快速路径，无状态串线和意外 5xx。
- 20 个请求同时提交同一 thread，只有一个执行，其余得到明确 `THREAD_BUSY`。
- 20 个请求重复同一 `runId`，外围能力最多调用一次。
- SSE 连接完成后租约、连接和任务释放，无持续增长。

该冒烟测试用于发现明显并发错误，不代表达到 500 请求/秒生产容量。接近正式规模前必须在真实网络、OpenGauss、模型和外围 Agent 上执行逐级压测至 500 请求/秒及 5000 在线背景，并记录 p50/p95/p99、错误率、连接池、CPU、内存和外围限流；容量不达标时再决定实例数和 Redis 等设施。

### 26.9 测试证据

每次验收报告必须列出：

- 实际 Python、Node 和全部关键依赖精确版本。
- 每条检查命令、退出码和汇总。
- 测试数量、跳过数量及每个 skip 的外部原因。
- 使用 Fake 还是生产 Delegate。
- 使用内存/PostgreSQL/OpenGauss 哪一种 Checkpointer。
- 未提供的真实协议和未执行的生产验证。

任何关键测试被 skip 都不能报告“全部完成”。

## 27. 开发顺序

只有本文被用户明确审核通过后，才按以下顺序开发：

1. **兼容性试验**：联网解析并锁定依赖；验证 LangGraph 1.x、LangChain 1.x、AG-UI、Vue 3 和 OpenAI 兼容本地模型的最小链路。
2. **工程骨架**：创建目录、质量配置、生产/测试装配边界和中文代码规范示例。
3. **Domain 与协议**：实现 Pydantic/Zod 模型、标识、错误和全部采购事件契约。
4. **Delegate 接口与 Fake**：不猜外围 HTTP，先完成可控成功/失败/流式 Fake。
5. **数据库边界**：完成逻辑迁移、Run/Action/租约/消息/记忆/Trace 接口；有环境时验证 OpenGauss Checkpointer。
6. **Graph Runtime**：完成场景生命周期、interrupt/resume、截止时间、幂等和 SSE 适配。
7. **模型与 ReAct**：实现 Prompt Catalog、OpenAI 兼容 Delegate 和仅 Scenario Tool 的路由。
8. **业务 Graph**：按智能分流、商品推荐 Subgraph、知识推荐顺序实现并逐路径集成测试。
9. **Vue 3 前端**：实现 AG-UI 事件、全部采购组件、Local Bridge、快照恢复和固定导航。
10. **全链路质量**：补齐 Trace、长期记忆、失败重试、E2E 和并发冒烟。
11. **部署**：完成原生虚拟机、Docker、迁移、场景过期、健康检查和生产镜像验证。
12. **真实接入**：每收到一份外围协议，就实现一个生产 Delegate 和契约测试；最后在目标环境完成生产验收。

每一步完成后必须运行当时已有的全部门禁。不得先写一个全耦合 Demo，再承诺以后拆层。

## 28. 两级完成标准

### 28.1 本地可运行完成

只有同时满足以下条件才可称为“本地可运行完成”：

- 后端和前端使用锁文件可重复安装、构建和启动。
- Vue 3 调用真实 FastAPI、AG-UI 适配和真实编译 LangGraph。
- ReAct 使用可配置 OpenAI 兼容接口；自动测试可替换为 Fake Model。
- 所有外部业务能力使用 `test_support` Fake，但路径、超时、重试和流式行为经过真实 Delegate 接口。
- 智能分流和知识推荐全部测试矩阵通过。
- Checkpoint、Action、恢复、长期记忆和 Trace 在本地测试实现上可观察。
- Chrome E2E、并发冒烟和所有静态门禁通过。
- 生产源码与测试代码分离，生产构建无 Fake。
- README 明确列出启动命令、Fake 数据和不属于生产验证的项目。

本地完成不得写成“系统已生产可用”。

### 28.2 生产接入完成

只有同时满足以下条件才可称为“生产接入完成”：

- 目标 OpenGauss 版本上的迁移、Psycopg、连接池、Checkpointer、interrupt/resume、锁和 Trace 全部通过。
- 真实 OpenAI 兼容模型完成结构化、Tool、流式、超时和备用策略测试。
- IOI、栏目、重复自采、搜索、知识和排队的正式协议均已获得并完成 Delegate 契约测试。
- 所有允许展示的外围流字段得到接口所有方确认，隐藏字段过滤测试通过。
- `HostPurchaseFormBridge` 与公司申购单页面真实加购成功。
- 三个导航目标、区域上下文和采购热线在目标页面验证。
- production Composition Root、镜像和虚拟机服务均无 Fake 或测试依赖。
- Nginx SSE、CORS、凭据、数据库权限、健康检查、优雅发布与回滚演练通过。
- 在生产等价环境完成全业务 Chrome E2E 和并发冒烟。
- 验收报告没有把外部阻塞项标成通过。

500 请求/秒完整容量不是首次生产接入通过门槛，但在业务量达到该目标前必须另行完成第 26.8 节真实容量测试。

## 29. 禁止事项与外部阻塞清单

### 29.1 开发禁止事项

后续开发 Agent 不得：

- 扫描、复制或依赖 `procumentagent_lite` 外的旧项目。
- 在本文审核通过前开始生产代码。
- 自研替代 LangGraph 的流程引擎。
- 让 ReAct 直接调用采购 Delegate 或决定关键业务分支。
- 用动态注册、反射扫描、Manifest、数据库配置或任意 import 字符串扩展 Tool。
- 给 Graph、Tool、State 或 Prompt 增加业务版本号。
- 在代码部署后自动恢复旧活动场景。
- 在节点中直接使用 HTTPX、Psycopg、SQL 或外围 JSON。
- 为一次性 Delegate 调用机械包装 Atomic Tool。
- 把测试 Fake、Mock Backend 或测试数据放入生产源码/镜像。
- 用 Mock Backend 代替真实 FastAPI/LangGraph 完成前端验收。
- 虚构任何尚未提供的外围接口协议。
- 将知识 value、固定排队文案或搜索结果交给模型改写/重排。
- 让加购调用后端 Agent 或结束推荐流程。
- 在用户等待、HTTP 调用或 SSE 期间持有数据库事务。
- 把凭据、隐藏推理、任意 HTML 或任意 URL 发给前端或写入 Trace。
- 因没有真实 OpenGauss 而把内存/PostgreSQL 测试标为 OpenGauss 通过。
- 为通过检查关闭严格类型、跳过关键测试或吞掉未知异常。

### 29.2 当前外部阻塞

以下信息不齐不会阻止本地 Fake 开发，但会阻止对应生产验收：

| 阻塞项 | 缺少内容 | 解锁的工作 |
|---|---|---|
| Python/npm 联网解析 | 可访问包仓库的开发环境 | 锁定精确最新版兼容依赖 |
| OpenGauss 环境 | 版本、DSN、权限、网络和测试库 | 驱动、迁移、Checkpointer、索引和并发验证 |
| 模型环境 | base URL、模型名、凭据、能力说明 | 真实 OpenAI 兼容模型验收 |
| IOI Agent | 请求、响应、鉴权、错误和流协议 | IOI 生产 Delegate |
| 栏目 Agent | 同上及多栏目稳定 ID 规则 | 栏目生产 Delegate |
| 重复自采 Agent | 同上及重复结果字段 | 探针生产 Delegate |
| 商品搜索 | 搜索词、栏目、分页、结果和排序协议 | 搜索生产 Delegate |
| 知识接口 | 全量 key/value、缓存条件和错误协议 | 知识生产 Delegate |
| 排队接口 | 用户/业务输入、数量字段和错误协议 | Queue 生产 Delegate |
| 公司申购单 | 加购宿主接口协议 | `HostPurchaseFormBridge` |
| 页面配置 | 三个目标 URL、user/region 提供方式、CORS 来源 | 真页面跳转和上下文验收 |
| 采购热线 | 正式固定引导文案或号码 | 无栏目分支生产文案 |
| 外围流展示审批 | 每个 Agent 哪些字段可展示 | 各 Delegate `expose_stream_to_ui` 开启 |

遇到阻塞时实现接口、Fake 和明确的 `NotConfigured` 路径即可。不得猜测完成真实映射，也不得因为阻塞而修改已确认业务规则。

## 30. 一次数据如何完整流转

### 30.1 自然语言启动新场景

以用户输入“我需要购买笔记本，用于研发办公，预算 9000 元，请推荐商品和采购模式”为例：

1. Chrome 前端取得页面提供的 `user_id` 和 `regionCode`。
2. `useSession` 读取或创建当前 `threadId`，`runController` 为本次请求生成新 `runId`。
3. AG-UI 协议适配器把用户消息、两个 ID 和 `pageContext` POST 到 `/api/v1/agent`。
4. FastAPI 使用 Pydantic 校验请求和 `X-User-ID`，拒绝客户端 Tool/State 注入。
5. Trace Collector 创建根 span；Database Delegate 在短事务中检查 `runId`、获得 thread 租约并登记 Run。
6. 会话当前没有活动场景，因此自然语言进入 ReAct；ReAct 只能看到静态 Scenario Tool 描述。
7. ReAct 选择 `smart_routing`。Scenario Tool 从服务端上下文取得原始文字，创建 `scenario_instance_id`，并启动智能分流 Graph。
8. Graph 先调用 Model Delegate 提取商品名称、用途和预算，并从页面上下文读取区域。
9. 字段齐全后依次执行 IOI、栏目和商品推荐等确定性节点；每个外围调用都经过对应 Delegate，记录独立 span，并受 15 秒/两次尝试/100 秒总截止时间约束。
10. 每个节点完成后 LangGraph Checkpointer 把 State 写入 OpenGauss。外部原始请求/响应进入 Trace，不塞入 State。
11. 到达商品选择等待点时，Graph 先把 `WaitRequest` 写入 State/Checkpoint 再 interrupt。运行器根据中断结果幂等保存 Actions，并发送商品与操作 `CUSTOM` 事件。
12. 本次 HTTP Run 发送 `RUN_FINISHED` 并结束 SSE；此时场景状态仍是 `waiting`，没有持续占用数据库事务或 Python 等待循环。
13. 在发送 `RUN_FINISHED` 前，应用层先保存本 Run 新增的消息/UI 块、把 Run 改为 `succeeded` 并释放 thread 租约；流生成器 `finally` 再关闭根 span、释放进程并发名额并批量写 Trace。
14. 最后一帧已经交给 ASGI 后，受管理异步任务调用记忆模型并通过 Database Delegate 合并该用户的个人记忆 JSON；失败不改变本次业务结果。

### 30.2 按钮启动新场景

步骤与上面相同，区别只有第 6 至 7 步：

1. 前端发送 `procurementInput.type=scenario_trigger` 和固定 `scenarioId`。
2. 后端从静态 Catalog 查找 ID。
3. 不调用 ReAct，直接执行对应 Scenario Tool。

因此按钮触发是准确且可预测的，自然语言触发则保留未来扩展更多 DAG 的能力。

### 30.3 用户选择或填写后恢复

以用户从多个栏目中选择一个为例：

1. 前端提交新的 `runId`、服务端签发的 `actionId` 和所选 `optionId`。
2. FastAPI/Pydantic 校验公开请求结构；应用层先按 `runId` 查重，保证幂等结果优先。
3. Database Delegate 只读取得 Action；提交值通过该 Action 绑定的 Pydantic 模型，并
   与 Action payload 中保存的 `option_ids` 做精确集合匹配。失败时尚未消费 Action。
4. `begin_run` 在一个短事务中再次查重、取得 thread 租约、锁定并复查 Action、消费
   Action、使同组 Action 失效并登记 Run。预读取后的竞态以这里的结果为准。
5. Graph Runner 根据活动场景取得 `scenario_instance_id`，使用相同
   `thread_id + checkpoint_ns` 加载最后 Checkpoint。
6. Runner 使用 LangGraph `Command(resume=...)` 恢复中断点。
7. Graph 按 `optionId` 从 Checkpoint 已保存候选中匹配一个栏目，不再调用栏目 Agent。
8. 后续节点、SSE、Trace、租约释放和异步记忆更新与新场景 Run 相同。

### 30.4 页面刷新恢复

1. 前端从 `sessionStorage` 取得当前 `threadId`。
2. 使用当前 `X-User-ID` 请求 session snapshot。
3. 后端先验证 thread 归属，再读取活动场景、可展示消息和已校验 UI 块；不向快照接口
   暴露或直接解析 LangGraph 原始 State。
4. 后端把它投影为稳定 Snapshot，绝不返回 Checkpoint 原始序列化内容。
5. 前端恢复消息、商品、Form/Options/Actions 和场景按钮可见状态。
6. 若场景已超过 24 小时或因部署过期，前端显示过期状态并允许创建新场景，旧 Action 不可提交。

### 30.5 结束与跳转

- IOI 节点发固定 Navigation 后，Graph 和场景都完成。
- 自行采购需要用户先点已签发按钮；恢复 Graph 后发 Navigation 并完成。
- 自定义采购进入时先调用 Queue，展示排队信息和按钮；只有用户点击按钮、恢复 Graph 并收到 Navigation 后才完成。
- 前端把固定 target 映射成部署 URL。导航发生在浏览器，Agent 不再执行其他动作。

### 30.6 各类数据最终在哪里

| 数据 | 权威位置 |
|---|---|
| 当前业务步骤和已选栏目 | LangGraph Checkpoint |
| 当前场景状态 | `scenario_instances` |
| 当前有效按钮/表单 | `pending_actions` + Checkpoint 的 `WaitRequest` |
| 用户与可展示助手消息 | `assistant_messages` |
| Run 幂等和结果状态 | `assistant_runs` |
| 个人长期记忆 | `user_memories.memory_json` |
| 调用输入输出、父子关系和耗时 | `trace_spans` |
| 知识全集短期缓存 | 各后端进程内存，默认 10 分钟 |
| 页面当前 thread | 浏览器 `sessionStorage`，后端仍校验归属 |
| 申购单中已加商品 | `PurchaseFormBridge` 对接的前端/宿主页面 |

同一份信息只能有一个权威来源。前端快照、展示组件和模型上下文都是投影或输入，不得反向覆盖 Checkpoint、外部业务结果或数据库归属。
