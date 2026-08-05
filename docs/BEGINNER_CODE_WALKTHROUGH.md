# 智能分流完整代码阅读指南（Python 新手版）

这份文档只讲一条真实链路：用户发送
“我需要购买研发笔记本，用于研发办公，预算 10000，请推荐商品和采购模式”，后端如何
从 HTTP 请求一路运行到智能分流结束。阅读时请按顺序往下看，不要先跳到某个 Node；
每一层都把工作交给下一层，后面的代码才能接上前面的结果。

本文使用当前代码的真实路径。后端生产代码已经分成两层：

- `core`：通用引擎，只负责“怎样可靠运行”。例如接收请求、记录耗时、启动/恢复
  LangGraph、保存 Checkpoint 和发 SSE。
- `business`：采购业务，只负责“要做什么”。例如判断 IOI、识别栏目、搜索商品和
  选择自行采购。

一个非常重要的阅读规则是：

```text
main.py → business/bootstrap.py → core 的通用对象 + business 的业务对象
业务节点可以使用 core，core 不能 import business
```

## 1. 先看一次请求长什么样

前端会向 `POST /api/v1/agent` 发送类似下面的 JSON，并在请求头携带 `X-User-ID`：

```json
{
  "threadId": "thread-001",
  "runId": "run-001",
  "messages": [
    {
      "id": "message-001",
      "role": "user",
      "content": "我需要购买研发笔记本，用于研发办公，预算10000，请推荐商品和采购模式"
    }
  ],
  "state": {},
  "tools": [],
  "context": [],
  "forwardedProps": {
    "pageContext": {
      "regionCode": "CN-SH",
      "locale": "zh-CN"
    },
    "procurementInput": null
  }
}
```

字段的直白解释：

| 字段 | 可以怎样理解 |
|---|---|
| `threadId` | 这一段连续会话的编号。用户补充预算、选择栏目时仍然使用同一个编号。 |
| `runId` | 这一次点击或发送文字的编号。网络重试时用它判断请求是否已经处理过。 |
| `messages` | 自然语言输入。本轮只看最后一条用户消息。 |
| `pageContext.regionCode` | 页面提供的区域编码。它不是用户身份，也不用于鉴权。 |
| `procurementInput` | 如果是按钮或表单请求，这里会有值；自然语言请求为 `null`。 |
| `state/tools/context` | 为兼容 AG-UI 保留，但本系统要求为空，不能相信浏览器传来的业务状态。 |

## 2. 程序启动时，谁把对象接好

### 2.1 `main.py` 是最外层入口

文件：[`backend/src/procurement_assistant/main.py`](../backend/src/procurement_assistant/main.py)

文件最后只有一个关键语句：

```python
app = build_production_app()
```

这里的 `app` 是 FastAPI 应用。`main.py` 不创建数据库连接、不创建 Graph，也不写采购
判断；它只是告诉 Uvicorn：“请使用 Business 的生产装配入口”。

### 2.2 `business/bootstrap.py` 是装配台

文件：[`business/bootstrap.py`](../backend/src/procurement_assistant/business/bootstrap.py)

可以把 `build_runtime()` 想成一张接线图。它做的事情按顺序是：

1. 创建 `CoreSettings` 和 `BusinessSettings`。前者只有超时、并发等通用配置，后者只有
   商品页大小、采购热线和外围 Agent 流展示开关。
2. 创建 `ActionInputRegistry`。这里明确登记“采购信息表单”“知识查询表单”“栏目选择”
   等输入模型。
3. 创建 `CoreWaitRequestFactory`，再包装成 Business 的等待点工厂。Core 负责生成
   Action ID 和 24 小时到期时间，Business 决定表单字段和按钮文案。
4. 创建商品推荐 Subgraph、缓存知识 Delegate 和两个场景的 `definition.py`。
5. 调用 `build_scenario_registry()`，把智能分流和知识推荐完整定义放进只读目录。
6. 把场景目录、Action 注册表和 Core 等对象传给 `GraphRunner`、`AgentApplication`、
   `ReactScenarioRouter`。
7. 注入 `ProcurementSnapshotPolicy`，告诉 Core 哪些业务 UI 块刷新后仍值得展示；Core
   不需要知道商品和排队事件的名字。
8. 创建记忆更新器、Trace 刷新器和 FastAPI 运行时容器。

这就是为什么新增普通采购业务时通常只改 `business`：Core 只接收已经装配好的对象。

### 2.3 一个场景的完整定义

文件：[`business/scenarios/smart_routing/definition.py`](../backend/src/procurement_assistant/business/scenarios/smart_routing/definition.py)

`SmartRoutingDependencies` 是一个“依赖清单”，把模型、IOI Delegate、栏目 Delegate、
排队 Delegate、商品子图和等待工厂列出来。它不是神秘容器，而是普通的 Python 数据类：
开发者一眼就能看出智能分流需要什么。

`build_smart_routing_definition()` 做三件事：

```python
nodes = SmartRoutingNodes(...)
graph = build_smart_routing_graph(nodes, checkpointer=...)
return ScenarioDefinition(
    scenario_id="smart_routing",
    display_name="智能分流",
    description="...",
    tool=StartSmartRoutingTool(),
    graph=graph,
)
```

- `nodes` 保存业务节点要用的 Delegate。
- `tool` 只负责创建第一份业务状态，不判断 IOI，也不调用外部接口。
- `graph` 是已经编译好的 LangGraph，运行时直接复用，不会每个请求重新构图。

`core/orchestration/scenarios.py` 中的 `ScenarioRegistry` 会在启动时检查：ID 是否为空、
Tool ID 是否和场景 ID 一致、Graph 是否真的有 `ainvoke()`。如果配置写错，服务启动就
失败，而不是等用户请求时才出现难查的错误。

## 3. HTTP 请求进入 FastAPI

### 3.1 `create_app()` 注册公共能力

文件：[`core/api/app.py`](../backend/src/procurement_assistant/core/api/app.py)

`create_app(runtime)` 接收已经装配好的运行时对象，然后：

1. 创建 FastAPI。
2. 把 `runtime` 放到 `app.state`，供健康检查和生命周期使用。
3. 注册 HTTP 中间件、异常处理器、Agent Router、Session Router 和 Health Router。

中间件 `assign_trace_id()` 会先给每个 HTTP 请求生成 `trace_id`，再调用 `call_next()`。
这个编号像快递单号：后面查总耗时、模型耗时或数据库耗时时，都用同一个编号查询。

### 3.2 `run_agent()` 是 HTTP 和业务世界的交界处

文件：[`core/api/agent.py`](../backend/src/procurement_assistant/core/api/agent.py)

函数注册方式如下：

```python
@router.post("/agent")
async def run_agent(...):
    ...
```

`@router.post` 的意思是：当收到 `POST /api/v1/agent` 时，FastAPI 调用下面这个函数。
`async def` 表示函数里面可以等待数据库、模型和网络，但等待时不会堵住整个 Python 进程。

参数由 FastAPI 自动准备：

- `http_request`：当前 HTTP 请求，可以读取中间件放进去的 `trace_id`。
- `run_input: RunAgentInput`：请求 JSON 已经转换、校验好的 Python 对象。
- `user_id`：通过 `Depends(get_user_id)` 从 `X-User-ID` 读取并校验。

如果 JSON 结构错误，函数体根本不会执行，统一由 `create_app()` 的校验异常处理器返回
固定错误；这比在业务节点中反复检查字段更清楚。

### 3.3 `RunAgentInput` 如何检查请求

文件：[`core/protocol/run_input.py`](../backend/src/procurement_assistant/core/protocol/run_input.py)

Pydantic 模型可以理解为“带自动检查功能的 Python 数据类”。例如：

```python
thread_id: ThreadId
run_id: RunId
messages: list[AGUIMessage] = Field(default_factory=list, max_length=200)
```

含义是：`thread_id` 和 `run_id` 必须符合 ID 格式，`messages` 没传时自动用空列表，最多
允许 200 条。

`@model_validator(mode="after")` 会在所有字段分别检查后再检查组合规则：

- 没有 `procurementInput` 时必须有最后一条用户消息；
- 有按钮或表单时不能同时携带 `messages`；
- 客户端传来的 `state`、`tools`、`context` 必须为空。

`original_user_text` 是一个只读属性。它从服务器已经校验过的最后一条用户消息取原文，
后面的 Scenario Tool 和 Graph 不接受模型自行生成的“替代原文”。

### 3.4 `get_user_id()` 做什么

文件：[`core/api/dependencies.py`](../backend/src/procurement_assistant/core/api/dependencies.py)

```python
x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None
```

这行告诉 FastAPI：从名为 `X-User-ID` 的请求头取值。当前按已确认方案不验签，但仍然
检查非空、长度和格式。区域编码只能作为页面上下文，绝不能代替 `user_id`。

## 4. 建立 Trace 和准入记录

### 4.1 `root_span` 是整条请求的总计时器

`run_agent()` 首先创建 `TraceCollector`，然后创建 `root_span`：

```python
root_span = collector.start_span(
    kind=SpanKind.HTTP,
    name="http.post_agent",
    target="POST /api/v1/agent",
    bind_as_parent=False,
)
```

不要把 `root_span` 理解成业务状态。它只是一个计时记录：开始时间、结束时间、错误、
首字节时间和最终结果时间。`bind_as_parent=False` 是因为 SSE 响应还没结束，路由函数和
后面的异步生成器可能不是同一个异步任务；代码会用 `parent_scope(root_span_id)` 明确
告诉子 span 谁是父节点。

总计时范围是：

```text
收到 HTTP 请求
  ├─ 准入数据库操作
  ├─ ReAct / Graph / Delegate
  ├─ SSE 逐帧发送
  └─ 最后一帧发送完成或浏览器断开
```

所以查到的总耗时比较接近用户真实等待时间。

### 4.2 容量限制

`runtime.capacity.try_acquire()` 尝试拿一个并发名额。如果当前同时在线/运行数量已经
达到配置上限，立即返回“系统当前请求较多”，不会继续访问数据库和外围 Agent。成功时
在 `finally` 里调用 `release()`，无论成功、失败还是断线都归还名额。

### 4.3 `application.admit()` 像取号台

文件：[`core/orchestration/application.py`](../backend/src/procurement_assistant/core/orchestration/application.py)

`admit()` 在 SSE 响应打开前做三件关键事情：

1. 查询同一个 `runId` 是否已经处理过。已存在就返回重复请求，避免网络重试重复采购。
2. 检查同一个 `threadId` 是否已经被另一请求占用。同一会话只允许一个 Run 执行。
3. 如果本次是按钮或表单，读取服务端签发的 `action_id`，用 `ActionInputRegistry` 校验
   输入，但此时还没有消费 Action。

随后调用 `database.begin_run()`。这是一个很短的数据库事务，里面原子完成 Run 登记、
thread 租约和 Action 消费。事务结束后才调用模型或外围 Agent，因此不会出现“一个
15 秒外部调用一直占着数据库事务”的问题。

## 5. 创建 SSE 事件传送带和运行上下文

准入成功后，`run_agent()` 创建一个 `asyncio.Queue`。可以把它理解成一条传送带：

```text
Graph / Application（生产者） → queue → stream_events（消费者） → 浏览器 SSE
```

业务节点只调用 `AGUIEventEmitter.text_message()` 或 `custom()`，不需要知道 HTTP、ASGI
或浏览器连接。`AGUIEventEmitter` 会自动补齐 `threadId`、`runId`、事件 ID 和递增序号。

接着创建 `ExecutionContext`：

```python
ExecutionContext(
    user_id=user_id,
    thread_id=run_input.thread_id,
    run_id=run_input.run_id,
    trace_id=trace_id,
    page_context=run_input.forwarded_props.page_context,
    deadline=RunDeadline.after(runtime.settings.run_deadline_seconds),
    trace=collector,
    events=emitter,
    clock=runtime.clock,
    ids=runtime.ids,
    settings=runtime.settings,
)
```

它是本次 Run 随身携带的“工具包”，不是智能分流的业务记事本：

- `page_context` 让节点拿到页面区域编码；
- `deadline` 是整次 Run 的倒计时，初始配置为 100 秒；
- `events` 发文字、表单、按钮和业务事件；
- `trace` 记录每一步耗时；
- `settings` 只含 Core 的超时和重试配置。

业务字段（商品名、栏目、预算）放在 LangGraph State，而不是放在这里，因此 Checkpoint
不会把数据库连接或事件发送器序列化进去。

## 6. `execute_application()` 和 `stream_events()` 同时工作

`run_agent()` 内部有两个重要函数。

### 6.1 生产者：`execute_application()`

它调用：

```python
result = await runtime.application.execute(...)
```

Application 会产生事件并把结果放进 `result_holder`。发生异常时，Application 负责发安全
的 `RUN_ERROR`、结束 Run；`execute_application()` 最后无论如何都放入 `_END_OF_STREAM`
这块“结束牌”，告诉消费者没有更多事件了。

### 6.2 消费者：`stream_events()`

它创建生产者任务，然后反复执行 `await queue.get()`。拿到一个 Pydantic 事件后，调用
`encode_sse_event()` 变成：

```text
data: {"type":"...", ...}\n\n
```

`yield` 会把这一帧交给 FastAPI；浏览器不必等整个 Graph 完成就能看到文字或表单。
读到 `_END_OF_STREAM` 后等待生产者结束，最后关闭 root span、释放容量并刷新 Trace。

## 7. Application 判断本次是哪一种输入

`AgentApplication._dispatch()` 先用 `database.get_active_scenario()` 查询当前会话是否有
活动场景，然后看 `forwardedProps.procurementInput` 的类型。

本次是自然语言，所以走第二条路：

1. 把最后一条用户消息保存到数据库；
2. 读取这个用户的个人长期记忆。记忆只辅助非关键的个性化表达和路由，不能替代采购
   规则；
3. 如果当前已有场景，先走场景切换确认；本次没有活动场景，于是调用 ReAct 路由；
4. ReAct 返回 `smart_routing` 后，调用 `GraphRunner.start()`。

### 7.1 ReAct 只选择场景

文件：[`core/orchestration/router/react_router.py`](../backend/src/procurement_assistant/core/orchestration/router/react_router.py)

路由器从 `ScenarioRegistry` 取得两个场景的 `display_name` 和 `description`，交给
`ModelDelegate.choose_scenario()`。模型能看到的工具只有：

```text
smart_routing：当用户希望购买商品，并需要推荐商品或采购方式时使用
knowledge_recommendation：当用户希望查询采购知识、规则或说明时使用
```

工具函数只返回静态场景 ID，不直接调用 IOI、搜索或数据库。模型返回后，路由器再次用
Registry 检查 ID 是否在白名单中；未知 ID 会变成澄清问题，不会动态 import 一个模块。

这一步的边界很重要：ReAct 只负责“进哪一个 DAG”，进入智能分流后，后续采购判断由
确定性 Graph 和业务节点完成。

## 8. GraphRunner 创建一次智能分流场景

文件：[`core/orchestration/graph_runner.py`](../backend/src/procurement_assistant/core/orchestration/graph_runner.py)

`start()` 的主要步骤如下：

1. `ScenarioRegistry.require("smart_routing")` 取得完整定义。
2. 生成 `scenario_instance_id`。同一个 thread 以后还可以再次开始新的场景实例，
   每次都有自己的编号。
3. 写入 `ScenarioRecord(status=RUNNING, expires_at=现在+24小时)`。
4. 把当前 `runId` 绑定到场景实例。
5. 调用 `StartSmartRoutingTool.create_initial_state()`。
6. 发出通用 `procurement.scene` 的 `RUNNING` 事件。
7. 调用统一 `_execute()` 驱动已经编译好的 Graph。

### 8.1 初始 State 是什么

文件：[`business/scenarios/smart_routing/state.py`](../backend/src/procurement_assistant/business/scenarios/smart_routing/state.py)

`SmartRoutingState` 可以理解为 LangGraph 在各节点之间传递的一本“流程记事本”。本次
初始内容大致是：

```python
SmartRoutingState(
    scenario_instance_id="scenario-...",
    input_source=InputSource.NATURAL_LANGUAGE,
    original_user_text="我需要购买研发笔记本...",
    region_code="CN-SH",
)
```

一开始 `product_name`、`purchase_purpose`、`budget_amount` 都是空的；后面的节点会返回
“需要修改哪些字段”，LangGraph 自动合并这些修改。`ExecutionContext` 不在 State 里，
因为它不是业务数据，也不应该写进 Checkpoint。

## 9. Graph 如何按顺序执行

文件：[`business/scenarios/smart_routing/graph.py`](../backend/src/procurement_assistant/business/scenarios/smart_routing/graph.py)

构图代码使用 LangGraph 的三个概念：

- `StateGraph(SmartRoutingState, context_schema=ExecutionContext)`：声明“这张图使用
  哪本记事本”和“运行时工具包是什么”；
- `add_node("名字", 函数)`：登记一个步骤；
- `add_edge` / `add_conditional_edges`：登记固定连线或条件连线。

`_bind()` 不是业务节点，它只是给每个节点包一个计时器。真正执行时，LangGraph 调用
包装后的函数，包装函数再调用 `SmartRoutingNodes` 的方法并记录 Node Span。

完整主线可以先看成下面这张文字图：

```text
START
  ↓
extract_purchase_fields
  ↓
prepare_missing_fields ──缺字段──→ wait_for_missing_fields ──恢复后回到这里
  │
  └─字段齐全→ judge_ioi
       ├─IOI=true → navigate_ioi → END
       └─IOI=false→ recognize_columns
                         ├─0 个 → handle_no_column → END
                         ├─1 个 → select_single_column
                         └─多个 → prepare_column_selection
                                      ↓
                                  wait_for_column_selection
                                      ↓
                              recommend_products
                                      ↓
                              present_recommendation
                         ┌────────────┴────────────┐
                    有商品，等待按钮                 无商品
                         │                           │
             换一批 / 追加 / 其他方式 / 结束       choose_procurement_mode
                         │                           │
                         └──────────────→ 采购方式判断
```

下面按真实执行顺序解释每个节点。

### 9.1 `extract_purchase_fields`

文件：`business/scenarios/smart_routing/nodes.py`，方法
`SmartRoutingNodes.extract_purchase_fields()`。

第一步先看页面有没有区域编码：

```python
if state.region_code is None and context.page_context.region_code is not None:
    updates["region_code"] = context.page_context.region_code
```

意思是：区域由页面上下文提供，不能让模型猜。如果本次是按钮进入，
`original_user_text is None`，直接返回区域，不调用模型。

本次有自然语言，于是创建 `PurchaseFieldExtractionInput`，只把用户原文交给结构化模型：

```python
extracted = await context.call_delegate(
    name="model.purchase_field_extraction",
    kind=SpanKind.MODEL,
    operation=invoke,
    input_data=request,
)
```

这里的 `operation=invoke` 是一个普通的异步函数。它里面才调用具体 `ModelDelegate`；
Core 的 `call_delegate()` 在外面统一加：

- 单次最多 15 秒；
- 使用剩余 Run 时间和 15 秒中较小的那个；
- 明确的临时错误最多重试一次；
- 每次尝试记录模型耗时；
- 如果外围有流，记录首字节和首段文字时间。

模型返回 `PurchaseFieldExtractionResult` 后，代码只把原来为空的字段填上，不覆盖已经
收集的字段。这对用户补充表单很重要：后续恢复时不会被旧原文重新覆盖。

### 9.2 `prepare_missing_fields`

`state.missing_required_fields` 按固定顺序检查：商品名称、采购用途、预算金额、区域编码。
如果都齐了，返回 `{"wait_request": None}`，条件边走向 `judge_ioi`；如果有缺失字段，
调用 Business 等待工厂创建表单。

等待工厂生成两类东西：

1. 要保存到 Checkpoint 的 `FormWaitRequest`，里面有标题、字段定义、过期时间和 Action；
2. 后续要发给前端的 `procurement.form` 事件。

### 9.3 `wait_for_missing_fields`

如果有缺字段，Graph 走到这个节点：

```python
resumed = interrupt(state.wait_request.model_dump(mode="json"))
```

`interrupt()` 的直白含义是“暂停这里，等用户下一次请求”。它不是抛出普通错误；
LangGraph 会把当前 State 和等待内容交给 Checkpointer 保存，然后把 `__interrupt__`
返回给 GraphRunner。

GraphRunner 发现中断后会：

1. 用 Core 的 Pydantic `WaitRequest` 解析它；
2. 把等待点和一次性 Action 写入数据库；
3. 发 `FORM` 事件给前端；
4. 把场景状态改成 `WAITING`；
5. 发 `SCENE=WAITING`；
6. 结束本次 Run 的 SSE。

用户填写表单后，前端再次 POST 一个新的 `runId`，带上原来的 `threadId` 和 `actionId`。
入口先校验表单，但只有 `begin_run()` 事务才真正消费 Action。GraphRunner.resume() 将
校验后的字段包装成 `Command(resume=GraphResumeInput(...))`，LangGraph 从原来的
`interrupt()` 位置继续，而不是从 START 重跑。

### 9.4 `judge_ioi`

字段齐全后，`_purchase_fields(state)` 组合出强类型 `PurchaseFields`，再创建
`IOIProcurementInput`。业务节点只调用 IOI Delegate，不知道 HTTP URL、JSON 字段映射或
重试细节：

```python
result = await context.call_delegate(
    name="agent.ioi_procurement",
    kind=SpanKind.AGENT,
    operation=invoke,
    expose_stream_to_ui=self._settings.ioi_expose_stream_to_ui,
    input_data=request,
)
```

最终只读取结构化 `result.is_ioi`。流式片段即使外围 Agent 返回，也不能代替最终判断。

### 9.5 IOI 分支

`routes.after_ioi()` 只读取 `state.is_ioi`：

- `True` 返回 `"ioi"`；
- `False` 返回 `"non_ioi"`；
- `None` 直接报服务端状态错误。

走 `navigate_ioi()` 时，后端发送固定的 `NavigationPayload(target=IOI_PURCHASE)`，然后把
状态设为 `COMPLETED`。后端不拼任意 URL，前端根据固定目标映射页面。GraphRunner 看到没有
`interrupt`，就把场景置为完成并发 `SCENE=COMPLETED`。

### 9.6 `recognize_columns`

非 IOI 时，代码用商品名称、区域编码、预算和可选币种创建栏目识别输入。注意这里没有
把商品用途传给栏目 Agent，也没有在商品推荐阶段把预算传给搜索接口；这些都是已经确认
的业务边界。

返回的所有 `ColumnCandidate` 都保存进 State。路由函数根据数量分三路：

- 0 个：`handle_no_column()` 发送采购热线文字并结束；
- 1 个：`select_single_column()` 直接选中，不再打断用户；
- 多个：创建选项等待点，让用户选一个。

### 9.7 多栏目选择和“不会再次调用原 Agent”

`prepare_column_selection()` 把所有候选的 `option_id`、栏目名和品类名写入等待点，
Action payload 还保存允许的 `option_ids` 集合。

用户选择后，入口的 `ActionInputRegistry` 先做一次精确集合校验；Graph 节点恢复后又在
State 的候选集合中找同一个 `option_id`。两层都通过才设置 `selected_column`。

这里没有 `recognize_columns()` 的再次调用，所以用户选栏目不会产生第二次外围 Agent
请求，也不会因为外部结果变化导致原候选消失。

## 10. 商品推荐子图和按钮等待

### 10.1 `recommend_products`

当 `selected_column` 已确定时，智能分流节点创建 `RecommendationState`，只放：

- 商品名称；
- 栏目名称；
- `user_id`；
- 页面区域编码；
- 可配置的每页数量（默认 3）。

预算故意不进入这个 State。然后调用已经在启动时编译好的
`business/scenarios/subgraphs/product_recommendation/graph.py`。

子图有两个节点：

1. `extract_search_terms`：模型根据商品名称和栏目拆出有效搜索词。换一批时已有
   `search_terms`，所以跳过模型。
2. `search_products`：把搜索词、栏目、用户、区域、页码和页大小交给搜索 Delegate。
   排序由搜索接口完成，后端只展示返回结果，不在 Agent 中重复排序。

### 10.2 `present_recommendation`

有商品时发送 Business 的 `procurement.products` 事件。商品模型先通过
`ProductView.from_domain()` 把 Decimal 价格转换为前端 JSON number，然后生成等待点。
等待点上的按钮可能包括：

- `换一批`；
- `追加其他商品`；
- `没有满意的商品，请为我推荐另外的采购方式`；
- `结束本次推荐`。

用户点击“加购”不经过 Agent。前端直接把商品加到申购单；这个点击不会消费后端等待点，
当前智能分流 Graph 也不需要中止，所以其他按钮仍然可以继续使用。

### 10.3 “换一批”

`advance_product_page()` 只把页码加一、清空当前商品和等待点、把结果状态设为未搜索。
原来的搜索词保留，下一次进入子图时跳过语义拆解，直接调用搜索接口下一页。

### 10.4 “追加其他商品”

`reset_for_appended_product()` 把商品名、用途、预算、栏目、推荐结果、重复自采结果和
排队数量全部清空，区域编码保留。然后连线回到 `extract_purchase_fields`，等价于在同一
场景实例里重新开始收集一个商品；它不会创建第二个并行场景，也不会自动复用旧商品字段。

### 10.5 “结束本次推荐”

`complete_recommendation()` 将状态设为 `COMPLETED`，Graph 走 END。这里不需要调用任何
外围接口，也不会修改已经由前端完成的加购。

## 11. 没有商品或用户要换采购方式时

`present_recommendation()` 如果商品列表为空，先发送“没有找到符合条件的商品”，然后连到
`choose_procurement_mode()`。如果用户点击“没有满意的商品，请为我推荐另外的采购方式”，
也会进入同一个节点。

`routes.procurement_mode()` 检查之前选中的栏目：

- 栏目不允许自采：直接进入 `enter_custom_purchase`；
- 栏目允许自采：进入 `check_duplicate_self_purchase`。

### 11.1 重复自行采购判断

`check_duplicate_self_purchase()` 调用重复自采探针，输入是商品名、栏目名和当前用户。

- `is_duplicate=True`：业务不允许重复自采，进入自定义采购；
- `is_duplicate=False`：创建“自行采购”按钮，等待用户点击。

### 11.2 用户点击自行采购

`wait_for_self_purchase()` 恢复后发送固定 `SELF_PURCHASE` 导航事件并结束场景。进入等待
状态时不提前跳转，用户不点击按钮就不会结束。

### 11.3 自定义采购和排队信息

所有进入自定义采购的分支都会经过同一条连线：

```text
enter_custom_purchase → load_custom_queue → prepare_custom_purchase → wait_for_custom_purchase
```

`load_custom_queue()` 调用排队信息接口。接口返回数量时发送固定文案：

```text
前面还有xx单在采购受理中哦～，审批完成后，采购将按顺序为您处理！
```

如果数量为空或没有排队号，不发送排队事件。此时场景仍然等待，展示排队信息并不代表
流程结束。用户点击“自定义采购”后，`wait_for_custom_purchase()` 才发送固定
`CUSTOM_PURCHASE` 导航并结束排队信息和场景。

## 12. GraphRunner 如何判断暂停还是结束

`GraphRunner._execute()` 取得 Registry 中的 Graph，使用下面的 LangGraph 配置：

```python
{
    "configurable": {
        "thread_id": context.thread_id,
        "checkpoint_ns": scenario.scenario_instance_id,
    }
}
```

`thread_id` 代表会话，`checkpoint_ns` 用场景实例隔离同一会话的多次场景。调用
`graph.ainvoke(initial_state, config=config, context=context)` 后：

- 有 `__interrupt__`：保存等待点、Action 和 `WAITING` 状态，发 UI 事件，本次 Run 结束；
- 没有 `__interrupt__`：读取 State 的最终状态，更新场景为 `COMPLETED`/`ABORTED`，发
  场景事件，本次 Run 正常结束。

外围 Delegate 超时或暂时不可用时，GraphRunner 不马上丢弃 Checkpoint，而是签发一个通用
“重试” Action。用户点击后传 `None` 给 `ainvoke()`，LangGraph 从失败节点之前的最后成功
Checkpoint 继续。协议错误、业务状态错误和不可重试错误则终止场景，避免错误状态永久
停留在 `WAITING`。

## 13. 事件如何到达浏览器和数据库

### 13.1 SSE

业务节点发出的事件先进入 `AGUIEventEmitter.events`，再进入本请求的 `asyncio.Queue`。
`stream_events()` 每拿到一条，就编码成 SSE 帧并 `yield`。因此浏览器可能按这个顺序收到：

```text
RUN_STARTED
procurement.scene = RUNNING
procurement.products / procurement.form / procurement.actions
procurement.scene = WAITING 或 COMPLETED
RUN_FINISHED
```

实际事件会根据分支不同而变化。

### 13.2 持久化展示结果

Application 的 `_persist_display_output()` 遍历本次新增事件：

- `TEXT_MESSAGE_CONTENT` 保存为 assistant message；
- `CUSTOM` 事件保存为 UI block。

这样页面刷新时可以从会话快照读取历史展示内容。前端点击商品“加购”是前端自己的申购
单操作，不会要求后端再执行一个 Agent 动作。

### 13.3 长期记忆

当 `RUN_FINISHED` 已经可以发送后，`run_agent()` 才在后台启动
`MemoryUpdater.update()`。它不会阻塞用户看到结果，也不会影响本次 Run 成败。

Business 记忆实现会：

1. 在事务外读取当前个人记忆；
2. 调用记忆模型生成 `MemoryPatch`；
3. 在短事务中重新读取最新 JSON 并合并增量。

Core 只知道 `MemoryUpdater` 这个接口和任务生命周期，不知道记忆字段代表采购偏好还是
别的业务含义。

## 14. 出错时如何读代码

遇到问题时按下面顺序查，不要一开始就改 Node：

1. HTTP 没返回：先看 `core/api/app.py` 的请求校验和异常处理。
2. 入口返回 409：看 `AgentApplication.admit()` 的 `runId`、thread 租约或 Action 消费。
3. SSE 已打开后失败：看 `AgentApplication.execute()` 和 `GraphRunner._execute()` 的
   错误分支。
4. 外部接口慢：查 Trace 中对应的 `agent.*`、`service.*` 或 `model.*` span；再看
   `ExecutionContext.call_delegate()` 的单次 15 秒和总 100 秒限制。
5. Graph 停在等待：看业务节点是否创建了正确 `WaitRequest`，再看 GraphRunner 是否保存
   Action 和 `WAITING` 状态。
6. 用户点击后无法恢复：先核对 `threadId`、`actionId`、`schema_id` 和 Action 是否已经
   被另一个请求消费，再看对应 `wait_for_*` 节点的操作编号。
7. 路由进入错误场景：查 `ScenarioRegistry` 描述、ReAct 返回值和服务端二次白名单校验。

## 15. 推荐的阅读顺序

如果你是 Python 新手，建议实际打开编辑器按下面顺序阅读：

1. [`main.py`](../backend/src/procurement_assistant/main.py)：只看一行入口。
2. [`business/bootstrap.py`](../backend/src/procurement_assistant/business/bootstrap.py)：看对象怎样连接。
3. [`core/api/agent.py`](../backend/src/procurement_assistant/core/api/agent.py)：看 HTTP、队列和 SSE。
4. [`core/protocol/run_input.py`](../backend/src/procurement_assistant/core/protocol/run_input.py)：看请求如何被检查。
5. [`core/orchestration/application.py`](../backend/src/procurement_assistant/core/orchestration/application.py)：看三种输入路径。
6. [`core/orchestration/graph_runner.py`](../backend/src/procurement_assistant/core/orchestration/graph_runner.py)：看启动、暂停和恢复。
7. [`business/scenarios/smart_routing/graph.py`](../backend/src/procurement_assistant/business/scenarios/smart_routing/graph.py)：看节点和连线。
8. [`business/scenarios/smart_routing/routes.py`](../backend/src/procurement_assistant/business/scenarios/smart_routing/routes.py)：看条件边。
9. [`business/scenarios/smart_routing/nodes.py`](../backend/src/procurement_assistant/business/scenarios/smart_routing/nodes.py)：按本文第 9～11 节逐个对照。
10. [`core/orchestration/runtime.py`](../backend/src/procurement_assistant/core/orchestration/runtime.py)：最后再看通用超时、重试和 Trace。

读完这条链路后，再看知识推荐；它复用同一个 Core 入口、Runner、Action 和 SSE，只在
Business 目录替换 State、Node、Graph 和 Delegate。
