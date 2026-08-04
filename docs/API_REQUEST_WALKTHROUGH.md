# 从 API 请求到页面展示：Python 新手阅读指南

这份指南只讲一件事：用户在页面发送一句话或点击一个按钮后，数据如何进入后端、经过
LangGraph，最后回到浏览器并显示出来。

建议第一次阅读时不要从 `composition.py` 的所有依赖开始，也不要马上钻进几百行的业务
节点。先沿本指南中的主线走通一遍，再选择自己关心的分支深入。

## 1. 先记住整条主线

```text
用户输入或点击按钮
    ↓
前端组装 RunAgentInput
    ↓
POST /api/v1/agent
    ↓
FastAPI 中间件分配 trace_id
    ↓
run_agent 接收并登记请求
    ↓
AgentApplication 判断输入属于哪条路
    ↓
GraphRunner 启动或恢复 LangGraph
    ↓
Graph 节点调用模型、外围 Agent、服务或数据库
    ↓
节点产生文字、表单、按钮、商品等 AG-UI 事件
    ↓
事件进入当前请求的 asyncio.Queue
    ↓
StreamingResponse 通过 SSE 逐条发给浏览器
    ↓
前端 reducer 把事件转换成页面状态
    ↓
React 根据新状态重新渲染，用户看到结果
```

## 2. 先认识几个编号

这些编号名字相似，但表示的范围不同。

| 名称 | 通俗含义 | 什么时候变化 |
| --- | --- | --- |
| `user_id` | 当前用户是谁 | 用户切换时变化 |
| `thread_id` | 当前这一段连续会话 | 新建会话时变化 |
| `run_id` | 用户本次发送或点击 | 每次 API 调用都变化 |
| `scenario_instance_id` | 本次智能分流或知识推荐流程 | 每次启动新场景时变化 |
| `trace_id` | 本次 API 调用的排障查询号 | 每次 API 调用都变化 |
| `span_id` | 调用链中某一个步骤的计时记录号 | 每记录一个步骤就变化 |

例如用户在一个智能分流场景中先发送需求，再填写缺失字段：

```text
同一个 user_id
同一个 thread_id
同一个 scenario_instance_id

第一次自然语言请求：run_id_1、trace_id_1
第二次表单请求：    run_id_2、trace_id_2
```

`run_id` 不是整个会话，也不是整个场景；它只代表一次 HTTP 处理。

## 3. 服务启动时发生什么

### 3.1 Uvicorn 找到 FastAPI 应用

先阅读 [`main.py`](../backend/src/procurement_assistant/main.py)：

```python
app = build_production_app()
```

启动命令中的 `procurement_assistant.main:app` 表示导入这个模块，并取得名为 `app` 的
FastAPI 对象。

### 3.2 装配数据库、模型、Graph 和应用服务

`build_production_app()` 位于
[`composition.py`](../backend/src/procurement_assistant/composition.py)。它像组装电脑一样，
把数据库 Delegate、模型 Delegate、GraphRunner、AgentApplication 等对象连接起来。

这一步只在服务启动时发生，不会在每次请求时重新创建全部 Graph。

### 3.3 注册 HTTP 路由

[`app.py`](../backend/src/procurement_assistant/api/app.py) 调用：

```python
app.include_router(build_agent_router(runtime))
```

`build_agent_router` 创建 Router，并把内部函数 `run_agent` 注册成：

```http
POST /api/v1/agent
```

`run_agent` 虽然定义在另一个函数里面，但 Router 会一直保存对它的引用，所以函数不会在
`build_agent_router` 返回后消失。

## 4. 前端如何发出请求

从 [`SessionProvider.tsx`](../frontend/src/assistant/SessionProvider.tsx) 的 `execute()` 开始。
页面发送文字、触发场景、提交表单和点击按钮，最终都会进入这个函数。

接着 [`runController.ts`](../frontend/src/agui/runController.ts) 生成新的 `runId`，并组装统一
请求。自然语言请求大致是：

```json
{
  "threadId": "thread_123",
  "runId": "run_456",
  "messages": [
    {
      "id": "message_789",
      "role": "user",
      "content": "我需要购买电脑，用于开发，预算一万元"
    }
  ],
  "state": {},
  "tools": [],
  "context": [],
  "forwardedProps": {
    "pageContext": {
      "regionCode": "CN-SH",
      "locale": "zh-CN",
      "currentPage": "/purchase"
    },
    "procurementInput": null
  }
}
```

最后 [`client.ts`](../frontend/src/agui/client.ts) 执行：

```typescript
fetch(`${apiBaseUrl}/api/v1/agent`, ...)
```

这一行是浏览器真正跨过网络进入 Python 后端的地方。

## 5. 请求进入 FastAPI 后先经过什么

### 5.1 中间件生成 trace_id

请求先经过 `app.py` 中的 `assign_trace_id()`。中间件可以理解为所有接口共用的门卫，它在
请求进入具体 Router 前执行：

```python
request.state.trace_id = runtime.ids.new("trace")
response = await call_next(request)
```

`call_next` 表示继续交给后面的请求校验和接口函数。响应返回后，中间件再把同一个
`trace_id` 放进 `X-Trace-ID` 响应头。

### 5.2 FastAPI 自动解析函数参数

主入口位于 [`agent.py`](../backend/src/procurement_assistant/api/agent.py)：

```python
async def run_agent(
    http_request: Request,
    run_input: RunAgentInput,
    user_id: Annotated[str, Depends(get_user_id)],
) -> Response:
```

FastAPI 会在进入函数体之前自动准备三个参数：

1. `http_request` 是原始 HTTP 请求对象；
2. 请求 JSON 经过 Pydantic 校验后成为 `run_input`；
3. `Depends(get_user_id)` 从 `X-User-ID` 请求头得到 `user_id`。

如果 JSON 字段缺失或类型错误，FastAPI 不会进入函数体，而是触发 `app.py` 中的请求校验
异常处理器，返回固定的 422 错误。

`RunAgentInput` 的详细规则在
[`run_input.py`](../backend/src/procurement_assistant/protocol/run_input.py)。

## 6. root_span 到底是什么

### 6.1 Trace 和 Span 的区别

把一次请求想成一次快递运输：

- `Trace` 是这件快递的完整物流记录；
- `Span` 是其中一个步骤，例如收件、分拣、运输或派送；
- `root_span` 是覆盖整段运输的最外层记录。

在本项目中，一次调用链大致是：

```text
root_span：POST /api/v1/agent 总耗时
├── database.run.begin：入口登记耗时
├── react.route：意图路由耗时
├── graph.smart_routing：Graph 总耗时
│   ├── node.extract_purchase_fields：字段提取节点耗时
│   │   └── model.purchase_field_extraction：模型耗时
│   ├── node.judge_ioi：IOI 节点耗时
│   │   └── agent.ioi_procurement：外围 Agent 耗时
│   └── database.checkpoint：Checkpoint 耗时
└── database.run.finish：Run 收尾耗时
```

`TraceCollector` 是本次请求的“记录本”，`SpanTimer` 是一个步骤的“秒表”，真正准备写入
数据库的数据是 `TraceSpan`。

### 6.2 为什么叫 root

每条 Span 都有自己的 `span_id`，并通过 `parent_span_id` 指向上一级。`root_span` 没有父
Span，其他步骤最终都挂在它下面，所以它是整棵调用树的根。

### 6.3 为什么手工调用 __aenter__ 和 __aexit__

普通步骤一般这样计时：

```python
async with collector.start_span(...) as span:
    result = await do_something()
```

进入 `async with` 时自动开始计时，离开时自动停止。

但是 `run_agent` 返回 `StreamingResponse` 时，响应正文还没有发送完。如果在函数返回时就
结束 root_span，只能记录“创建 StreamingResponse 用了多久”，不能记录用户真正等待了
多久。因此代码手工执行：

```python
await root_span.__aenter__()   # API 开始处理时启动
...
await root_span.__aexit__(...) # SSE 完成或断线时停止
```

这样 `root_span.duration_ms` 才覆盖完整的流式响应生命周期。

### 6.4 root_span 额外记录哪些时间

- `first_byte_ms`：第一条 SSE 事件产生用了多久；
- `first_text_delta_ms`：用户看到第一段助手文字用了多久；
- `final_result_ms`：完整业务结果生成用了多久；
- `duration_ms`：整条响应最终结束用了多久。

这几个值能区分“很快有进度但最终较慢”和“用户长时间什么都看不到”。

## 7. 正式处理前为什么还要 admit

`run_agent` 先调用 `AgentApplication.admit()`。可以把它理解为“受理登记”，主要检查：

1. `run_id` 是否已经处理过；
2. 同一个 `thread_id` 是否正在执行另一请求；
3. 按钮或表单对应的一次性 Action 是否存在、属于当前用户并且尚未消费；
4. 在数据库登记本次 Run，并短暂占用当前 thread。

`admit()` 返回时数据库事务已经结束。随后等待模型或外围 Agent 时，不会一直占着入口
事务。

必须在 SSE 开始前完成登记，因为此时还能返回准确的 HTTP 400、409 或 503。一旦 SSE
已经以 HTTP 200 打开，后续错误只能作为流中的 `RUN_ERROR` 事件返回。

## 8. 为什么同时有 execute_application 和 stream_events

处理过程需要同时做两件事：

- 生产事件：运行应用层和 Graph；
- 消费事件：把已经产生的事件立即发送给浏览器。

`agent.py` 为本次请求创建一个 `asyncio.Queue`，它像一条传送带：

```text
execute_application                 stream_events
业务生产者                           SSE 消费者
      │                                  ↑
      └── event_sink → asyncio.Queue ────┘
```

`asyncio.create_task(execute_application())` 启动生产者。它不是自动创建新线程，而是让两个
异步任务在遇到 `await` 时轮流获得执行机会。

消费者循环等待：

```python
event = await queue.get()
yield encode_sse_event(event)
```

- `await queue.get()`：暂时没有事件就等待，并让生产者继续运行；
- `yield`：把当前这一帧交给 FastAPI 发送，然后还可以继续产生下一帧；
- `_END_OF_STREAM`：生产者放入的结束牌，消费者读到后退出循环。

如果没有 `_END_OF_STREAM`，业务完成后消费者仍会永远等待下一条事件。

## 9. AgentApplication 如何选择处理路径

阅读 [`application.py`](../backend/src/procurement_assistant/orchestration/application.py) 的
`_dispatch()`。它只有三条主路。

### 9.1 页面场景入口按钮

`procurement_input` 是 `ScenarioTriggerInput` 时，按钮已经明确告诉后端启动智能分流还是
知识推荐，因此直接调用：

```python
self._runner.start(...)
```

### 9.2 用户自然语言

`procurement_input is None` 表示自然语言。应用层会：

1. 保存用户原文；
2. 读取这个用户的长期记忆；
3. 若已有活动场景，先处理是否切换场景；
4. 若没有活动场景，调用 ReAct Router 判断智能分流或知识推荐；
5. 调用 `GraphRunner.start()` 启动识别出的场景。

### 9.3 流程按钮或表单

`ActionInput` 或 `FormSubmitInput` 表示用户正在回答 Graph 之前提出的问题，例如选择栏目。
应用层验证 Action 属于当前活动场景后调用：

```python
self._runner.resume(...)
```

Graph 会从上次 Checkpoint 继续，而不是从开头重跑。

## 10. GraphRunner 如何执行 LangGraph

阅读 [`graph_runner.py`](../backend/src/procurement_assistant/orchestration/graph_runner.py)。

### 10.1 start

`start()` 创建新的 `scenario_instance_id`、保存场景记录、生成初始 State，然后进入统一的
`_execute()`。

### 10.2 真正执行

真正进入 LangGraph 的代码是：

```python
raw_result = await graph.ainvoke(
    graph_input,
    config=config,
    context=context,
)
```

- `graph_input` 是初始状态或用户恢复命令；
- `config` 告诉 Checkpointer 当前 thread 和场景实例；
- `context` 是运行工具包，包含事件发射器、Trace、用户信息和总截止时间。

### 10.3 interrupt

Graph 节点调用 `interrupt()` 表示“我现在缺少用户输入，不能继续”。例如栏目有多个时，
流程需要用户选择一个栏目。

GraphRunner 收到 `__interrupt__` 后会：

1. 校验等待要求；
2. 保存等待点和一次性 Action；
3. 发出表单、选项或按钮事件；
4. 把场景状态改成 `WAITING`；
5. 结束当前 Run，但不结束整个场景。

用户下一次提交后，会产生新的 `run_id`，再由 `resume()` 从这个等待点继续。

### 10.4 END

没有 interrupt 表示 Graph 已经走到 `END`。GraphRunner 将场景更新为 `COMPLETED` 或其他
终态，并发出场景结束事件。

## 11. 如何阅读具体业务流程

先读 Graph，再读节点实现，不要反过来。

智能分流的图在
[`smart_routing/graph.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/graph.py)：

- `add_node`：登记一个处理步骤；
- `add_edge`：固定连接到下一步；
- `add_conditional_edges`：根据 `routes.py` 的判断选择分支；
- `START`：场景入口；
- `END`：场景结束。

先顺着边了解整体顺序，再到
[`smart_routing/nodes.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/nodes.py)
查看某一个步骤做了什么。

知识推荐的图在
[`knowledge/graph.py`](../backend/src/procurement_assistant/orchestration/scenarios/knowledge/graph.py)，节点在
[`knowledge/nodes.py`](../backend/src/procurement_assistant/orchestration/scenarios/knowledge/nodes.py)。

## 12. 业务结果如何变成前端事件

Graph 节点不直接写 HTTP socket，而是调用 `ExecutionContext.events`：

```python
await context.events.text_message("未找到相关知识")
```

[`emitter.py`](../backend/src/procurement_assistant/protocol/emitter.py) 会把它包装成标准 AG-UI
事件，并调用 `agent.py` 提供的 `event_sink` 放入队列。

[`sse.py`](../backend/src/procurement_assistant/api/sse.py) 再把事件编码为：

```text
data: {"type":"TEXT_MESSAGE_CONTENT",...}

```

空行表示当前 SSE 帧结束。

## 13. 前端怎样把事件显示给用户

[`client.ts`](../frontend/src/agui/client.ts) 持续读取 `response.body`。网络一次读取的内容不
一定正好是一帧，所以先放进 `buffer`，再按空行切分完整 SSE 帧。

每一帧经过 JSON 和 Zod 校验后交给
[`eventReducer.ts`](../frontend/src/agui/eventReducer.ts)。Reducer 可以理解为事件翻译器：

- `TEXT_MESSAGE_CONTENT`：追加助手文字；
- `procurement.form`：设置当前表单；
- `procurement.options`：设置可选栏目；
- `procurement.products`：设置商品列表；
- `procurement.navigation`：准备页面跳转；
- `RUN_FINISHED`：结束页面上的加载状态。

Reducer 返回新的页面状态，React 组件自动重新渲染，用户最终看到结果。

## 14. 为什么 return StreamingResponse 不代表业务已经完成

这行代码：

```python
return StreamingResponse(stream_events(), ...)
```

返回的是一个“响应生成方案”，不是已经生成好的完整响应正文。之后 FastAPI/ASGI 才开始
迭代 `stream_events()`：

```text
run_agent 返回 StreamingResponse 对象
    ↓
ASGI 开始迭代 stream_events
    ↓
每次 yield 发送一帧
    ↓
生成器结束，HTTP 响应正文才真正完成
```

这也是 root_span 不能在 `run_agent` 返回时就关闭的原因。

## 15. 建议的第一次调试顺序

可以按照下面顺序打断点，每次只关心少量变量。

1. `api/agent.py → run_agent`
   - 看 `user_id`、`run_input.thread_id`、`run_input.run_id`。
2. `orchestration/application.py → admit`
   - 看是否返回 `AdmissionStatus.ACCEPTED`。
3. `orchestration/application.py → _dispatch`
   - 看 `procurement_input` 属于哪一种输入。
4. `orchestration/graph_runner.py → _invoke_graph_and_finalize`
   - 看传给 `graph.ainvoke` 的 `graph_input`。
5. 某个 `scenarios/.../nodes.py` 业务节点
   - 看进入节点的 `state` 和节点返回的更新字典。
6. `protocol/emitter.py → _publish`
   - 看产生了哪一种 AG-UI 事件。
7. `api/agent.py → event_sink`
   - 确认事件进入当前请求队列。
8. `api/agent.py → stream_events` 的 `yield`
   - 确认事件已编码成 SSE。
9. `frontend/src/agui/client.ts → parseFrame`
   - 确认浏览器收到了同一事件。
10. `frontend/src/agui/eventReducer.ts → reduceAGUIEvent`
    - 看事件最终修改了哪个页面状态字段。

## 16. 阅读这些 Python 语法时怎么理解

### `async def` 与 `await`

`async def` 定义异步函数。`await` 等待数据库或网络时会暂时让出执行权，使服务可以处理
其他请求。它不等于自动新建线程，也不等于所有代码自动并行。

### 定义在函数里面的函数

`run_agent`、`event_sink`、`execute_application` 和 `stream_events` 都是内部函数。内部函数
可以直接使用外层函数中的 `runtime`、`queue`、`root_span` 等变量，这种“记住外部变量”
的能力叫闭包。

### `@router.post("/agent")`

这是装饰器。`build_agent_router` 执行时，装饰器把下面的 `run_agent` 函数登记到 Router。
以后匹配到该 URL 和 HTTP 方法时，FastAPI 就调用它。

### `async with`

异步上下文管理器。进入代码块时启动资源或计时，离开时统一关闭。即使代码块报错，退出
逻辑也会执行，因此适合连接、事务和 Span。

### `try / except / finally`

- `try`：执行可能失败的处理；
- `except`：按错误类型处理；
- `finally`：无论成功、失败或取消都执行，适合释放容量和关闭计时器。

### `yield`

`return` 一次返回最终结果；`yield` 每次返回一部分后保留函数现场，下次可以继续。在本
项目中，每次 yield 返回一帧 SSE。

### `isinstance`

判断对象实际属于哪种类型。`_dispatch()` 使用它区分场景入口、按钮和表单请求。

### `Depends(get_user_id)`

FastAPI 的依赖调用。进入 `run_agent` 前，FastAPI 先执行 `get_user_id`，成功后把返回值
作为 `user_id` 参数；失败则直接走异常处理。

## 17. 推荐阅读顺序

第一次建议按下面顺序，每个文件只读本指南提到的函数：

1. `frontend/src/agui/runController.ts`
2. `frontend/src/agui/client.ts`
3. `backend/src/procurement_assistant/main.py`
4. `backend/src/procurement_assistant/api/app.py`
5. `backend/src/procurement_assistant/protocol/run_input.py`
6. `backend/src/procurement_assistant/api/agent.py`
7. `backend/src/procurement_assistant/orchestration/application.py`
8. `backend/src/procurement_assistant/orchestration/graph_runner.py`
9. 对应场景的 `graph.py`、`routes.py`、`nodes.py`
10. `backend/src/procurement_assistant/protocol/emitter.py`
11. `backend/src/procurement_assistant/api/sse.py`
12. `frontend/src/agui/eventReducer.ts`

先弄清数据“去了哪里”，再研究每个类内部“如何实现”，会比从 import 和构造函数逐行往下
读容易很多。
