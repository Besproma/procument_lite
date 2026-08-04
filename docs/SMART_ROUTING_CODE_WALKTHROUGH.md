# 智能分流完整代码走查（面向 Python 初学者）

这是一份“拿着代码逐步走”的说明。目标不只是说明业务规则，还要讲清楚每一段代码为什么
存在、数据什么时候变化、用户什么时候需要再次点击页面，以及场景最终如何结束。

建议阅读时同时打开这些文件：

- [`api/agent.py`](../backend/src/procurement_assistant/api/agent.py)：HTTP 和 SSE 总入口；
- [`orchestration/application.py`](../backend/src/procurement_assistant/orchestration/application.py)：输入分流；
- [`smart_routing/state.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/state.py)：流程记事本；
- [`smart_routing/graph.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/graph.py)：节点和连线；
- [`smart_routing/routes.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/routes.py)：条件分支；
- [`smart_routing/nodes.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/nodes.py)：每个业务步骤；
- [`product_recommendation`](../backend/src/procurement_assistant/orchestration/subgraphs/product_recommendation)：商品搜索子图。

## 1. 先看完整流程

```text
用户输入：我需要购买电脑，用于开发，预算 10000
       │
       ▼
POST /api/v1/agent
       │
       ▼
AgentApplication._dispatch
       │
       ▼
GraphRunner.start("smart_routing")
       │
       ▼
extract_purchase_fields
       │
       ▼
prepare_missing_fields
       │
       ├── 还有必填字段 ──► wait_for_missing_fields
       │                         │
       │                         └─ interrupt：保存表单，等待下一次 API 请求
       │
       └── 字段齐全 ──────► judge_ioi
                              │
                              ├── is_ioi=True  ──► navigate_ioi ──► END
                              │
                              └── is_ioi=False ─► recognize_columns
                                                       │
                         ┌─────────────────────────────┼───────────────────────────┐
                         │                             │                           │
                    0 个栏目                        1 个栏目                  多个栏目
                         │                             │                           │
              handle_no_column                  select_single_column     prepare_column_selection
                         │                             │                           │
                        END                    recommend_products     wait_for_column_selection
                                                       │                           │
                                                       └─────────────┬─────────────┘
                                                                     ▼
                                                           recommend_products
                                                                     │
                                                        商品推荐 Subgraph
                                                        （拆搜索词 → 搜索）
                                                                     │
                                                       present_recommendation
                                                                     │
                         ┌───────────────────────────────────────────┴──────────────┐
                         │                                                          │
                    有商品                                                       无商品
                         │                                                          │
              wait_for_recommendation_action                            choose_procurement_mode
                         │                                                          │
       ┌─────────┬────────────┬──────────────┐                       ┌──────────────┴─────────────┐
       │         │            │              │                       │                            │
     换一批   追加商品     其他采购方式    结束推荐               允许自采                     不允许自采
       │         │            │              │                       │                            │
  advance_page  reset    choose_mode   complete                  重复自采探针            enter_custom_purchase
       │         │            │                                      │                            │
       └──再搜───┘            │                         ┌────────────┴────────────┐               ▼
                               │                         │                         │        load_custom_queue
                               │                      不重复                    重复               │
                               │                         │                         │               ▼
                               │                    自行采购按钮              自定义采购     prepare_custom_purchase
                               │                         │                         │               │
                               │                        END                        └───────────────┘
                               └───────────────────────────────────────────────────────────────────
```

图中的 `END` 表示 Graph 走完。如果节点走到 `interrupt`，只是本次 HTTP Run 暂停等待用户，
场景还没有完成；用户下一次点击会使用新的 `run_id` 恢复同一个场景。

## 2. 先分清 Input、State 和 Event

### 2.1 Input：本次用户做了什么

Input 是一次请求带进来的内容，例如用户原文、按钮编号、表单值和页面区域。它只代表
“这一次用户做了什么”。

### 2.2 State：流程已经知道什么

`SmartRoutingState` 是流程的共享记事本，会在节点之间传递，也会在等待用户时写入
Checkpoint。例如商品名已经收集到，下一次请求就不用重新猜。

### 2.3 Event：页面应该显示什么

Event 是后端告诉前端“请显示什么”，例如文字、表单、栏目选项、商品列表或页面跳转。
Event 不是下一步业务输入；用户点击 Event 里的按钮后，浏览器才发出新的 API 请求。

```text
请求 Input ──► Graph 节点读取 State
                         │
                         ├─ 返回字典：更新 State
                         └─ 发出 Event：更新页面
```

## 3. 自然语言如何进入智能分流

基础 HTTP 代码已经在
[`API_REQUEST_WALKTHROUGH.md`](API_REQUEST_WALKTHROUGH.md) 逐步解释，这里只重复智能分流
需要知道的接力关系。

### 3.1 前端生成请求

[`runController.ts`](../frontend/src/agui/runController.ts) 为本次操作生成新的 `runId`，把
自然语言放在 `messages` 最后一项，并把 `procurementInput` 设成 `null`。

### 3.2 API 入口登记

[`run_agent()`](../backend/src/procurement_assistant/api/agent.py) 先调用 `admit()`，检查重复
Run、会话是否忙、Action 是否有效，并登记本次 Run。登记成功后才打开 SSE。

### 3.3 应用层识别输入类型

`AgentApplication._dispatch()` 的核心代码：

```python
if procurement_input is None:
    original_text = request.original_user_text
    route = await self._router.route(...)
    return await self._runner.start(
        scenario_id=route.scenario_id,
        input_source=InputSource.NATURAL_LANGUAGE,
        original_user_text=original_text,
        context=context,
    )
```

逐行理解：

1. `procurement_input is None`：没有按钮或表单，说明是自然语言；
2. `original_text`：取得后端认可的最后一条用户原文；
3. `_router.route`：ReAct 只负责选择场景；
4. `route.scenario_id`：选择结果，例如 `smart_routing`；
5. `_runner.start`：创建智能分流场景，把原文交给初始 State。

如果页面直接点击“智能分流”按钮，输入是 `ScenarioTriggerInput`，应用层跳过 ReAct，直接
使用按钮指定的 `scenario_id`。

## 4. 服务启动时怎样装好智能分流

[`composition.py → build_runtime()`](../backend/src/procurement_assistant/composition.py) 在服务
启动时执行：

```python
catalog = build_scenario_catalog()
waits = WaitRequestFactory(...)
product_nodes = ProductRecommendationNodes(...)
product_graph = build_product_recommendation_graph(product_nodes)
smart_nodes = SmartRoutingNodes(..., product_graph=product_graph, waits=waits)
graphs = {
    "smart_routing": build_smart_routing_graph(smart_nodes, checkpointer=...),
}
runner = GraphRunner(..., graphs=graphs, ...)
application = AgentApplication(..., runner=runner, ...)
```

逐行解释：

- `catalog`：建立场景名称和 Scenario Tool 的静态目录；
- `waits`：统一生成表单、选项、按钮和24小时过期时间；
- `product_nodes`：准备商品推荐需要的模型和搜索服务；
- `product_graph`：编译“拆搜索词 → 搜索”的小 Graph；
- `smart_nodes`：把 IOI、栏目、重复探针、排队等 Delegate 注入节点集合；
- `graphs`：编译完整智能分流 Graph；
- `runner`：保存编译好的 Graph，负责启动、暂停和恢复；
- `application`：保存 Runner，接收 API 层传来的请求。

这些代码只在启动时运行一次，请求到来时不会重新构建 Graph。

## 5. Scenario Tool：创建第一份 State

文件：[`start_smart_routing.py`](../backend/src/procurement_assistant/orchestration/tools/start_smart_routing.py)

### 第1～5行：说明和导入

```python
"""智能分流 Scenario Tool。"""

from procurement_assistant.domain.lifecycle import InputSource
from ...smart_routing.state import SmartRoutingState
from ...run_input import PageContext
```

- 模块文档说明这个文件的用途；
- `InputSource` 表示按钮进入还是自然语言进入；
- `SmartRoutingState` 是要创建的流程状态；
- `PageContext` 里有前端提供的区域编码。

### 第8～11行：工具类和编号

```python
class StartSmartRoutingTool:
    """创建智能分流初始 State，后续步骤全部交给确定性 Graph。"""

    tool_id = "smart_routing"
```

- `class` 定义一类对象；
- `tool_id` 是静态场景编号，Catalog 和 ReAct 都用它找到智能分流；
- 这个 Tool 只创建初始状态，不做 IOI 或栏目判断。

### 第13～20行：方法参数

```python
def create_initial_state(
    self,
    *,
    scenario_instance_id: str,
    input_source: InputSource,
    original_user_text: str | None,
    page_context: PageContext,
) -> SmartRoutingState:
```

- `self` 表示当前 Tool 对象；
- `*` 表示后面的参数必须写参数名，避免顺序传错；
- `scenario_instance_id` 是本次场景实例编号；
- `input_source` 是入口来源；
- `original_user_text` 是用户原文，按钮进入时允许为空；
- `page_context` 是页面上下文；
- `-> SmartRoutingState` 表示返回严格状态对象。

### 第23～28行：创建状态

```python
return SmartRoutingState(
    scenario_instance_id=scenario_instance_id,
    input_source=input_source,
    original_user_text=original_user_text,
    region_code=page_context.region_code,
)
```

每一行都是把入口数据放进第一份 State。这里不调用大模型，也不猜商品名；字段提取由
后面的节点负责。

## 6. SmartRoutingState：共享记事本逐行看

文件：[`state.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/state.py)

### 6.1 导入和类配置

```python
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
```

- `Decimal` 用精确十进制保存预算，避免浮点误差；
- `BaseModel` 提供 Pydantic 校验；
- `ConfigDict` 配置模型；
- `Field` 添加“不能小于0”等约束。

```python
class SmartRoutingState(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

- 状态继承 Pydantic；
- `extra="forbid"` 禁止未声明字段，拼错字段会立刻报错。

### 6.2 场景基本字段

```python
scenario_instance_id: str
status: ScenarioStatus = ScenarioStatus.RUNNING
input_source: InputSource
original_user_text: str | None = None
item_sequence: int = Field(default=1, ge=1)
```

- `scenario_instance_id`：本次场景实例编号；
- `status`：默认正在执行；
- `input_source`：按钮或自然语言；
- `original_user_text`：原始用户文字；
- `item_sequence`：同一场景中第几个商品，追加商品时加1；`ge=1` 表示最小值为1。

### 6.3 必填采购字段

```python
product_name: str | None = None
purchase_purpose: str | None = None
budget_amount: Decimal | None = Field(default=None, ge=0)
currency: str | None = None
region_code: str | None = None
```

- 商品名称、采购用途、预算和区域是继续流程前的必填信息；
- 币种允许为空；
- `None` 表示还没有收集到；
- 预算不能小于0。

### 6.4 各业务阶段结果

```python
is_ioi: bool | None = None
column_candidates: tuple[ColumnCandidate, ...] = ()
selected_column: ColumnCandidate | None = None
recommendation: RecommendationState | None = None
duplicate_self_purchase: bool | None = None
entered_custom_purchase: bool = False
queue_count: int | None = Field(default=None, ge=0)
navigation_target: NavigationTarget | None = None
```

逐行含义：

- `is_ioi`：IOI Agent 的结论；`None` 表示尚未判断；
- `column_candidates`：栏目 Agent 返回的全部候选；
- `selected_column`：最终选中的一个栏目；
- `recommendation`：商品推荐子图的分页和商品结果；
- `duplicate_self_purchase`：重复自采探针结论；
- `entered_custom_purchase`：是否已进入自定义采购；
- `queue_count`：排队数量，没查到时为 `None`；
- `navigation_target`：最终固定跳转目标。

### 6.5 用户等待相关字段

```python
wait_request: WaitRequest | None = None
selected_action: ActionOperation | None = None
recoverable_error: RecoverableError | None = None
```

- `wait_request`：当前需要展示的表单、选项或按钮；
- `selected_action`：用户恢复时选择了什么操作；
- `recoverable_error`：可恢复外围失败的信息。

### 6.6 缺失字段属性

```python
@property
def missing_required_fields(self) -> tuple[str, ...]:
    missing: list[str] = []
    if self.product_name is None:
        missing.append("productName")
    if self.purchase_purpose is None:
        missing.append("purchasePurpose")
    if self.budget_amount is None:
        missing.append("budgetAmount")
    if self.region_code is None:
        missing.append("regionCode")
    return tuple(missing)
```

逐行解释：

1. `@property` 让方法像只读属性一样调用；
2. 返回类型是字符串元组；
3. `missing` 从空列表开始；
4. 依次检查商品、用途、预算和区域；
5. 缺哪个就加入对应的前端字段 ID；
6. 最后转成不可随意修改的元组返回；
7. 币种没有出现在这里，因此不是必填字段。

## 7. graph.py：节点和连线逐行看

文件：[`graph.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/graph.py)

### 7.1 NodeMethod 类型别名

```python
NodeMethod = Callable[
    [SmartRoutingState, ExecutionContext],
    Awaitable[dict[str, Any]],
]
```

它只是给复杂类型取名：业务节点接收 State 和 Context，异步返回一个“要更新哪些字段”的
字典。类型别名不会执行任何业务。

### 7.2 `_bind` 包装业务节点

```python
def _bind(method: NodeMethod):
    async def wrapped(state, runtime):
        async with runtime.context.trace.start_span(...) as span:
            result = await method(state, runtime.context)
            span.set_output(result)
            return result
    return wrapped
```

逐行解释：

1. `_bind` 接收一个普通业务方法；
2. `wrapped` 是 LangGraph 实际调用的内部函数；
3. `async with` 给该节点建立独立计时记录；
4. `await method(...)` 真正执行 `nodes.py` 中的方法；
5. `set_output` 保存节点返回值供耗时查询；
6. `return result` 把更新交给 LangGraph 合并进 State；
7. 最后把包装后的函数返回给 Graph。

### 7.3 创建 Graph

```python
graph = StateGraph(
    SmartRoutingState,
    context_schema=ExecutionContext,
)
```

- 第一项说明共享业务状态类型；
- `context_schema` 说明每个节点能拿到的运行工具包类型；
- 这一行只是创建构建器，还没有执行节点。

### 7.4 每一条 `add_node`

| Graph 节点名 | 对应方法 | 用途 |
| --- | --- | --- |
| `extract_purchase_fields` | `extract_purchase_fields` | 从原文提取字段 |
| `prepare_missing_fields` | `prepare_missing_fields` | 准备缺失字段表单 |
| `wait_for_missing_fields` | `wait_for_missing_fields` | 等用户填表 |
| `judge_ioi` | `judge_ioi` | 调用 IOI Agent |
| `navigate_ioi` | `navigate_ioi` | 跳转 IOI 页面 |
| `recognize_columns` | `recognize_columns` | 调用栏目 Agent |
| `handle_no_column` | `handle_no_column` | 无栏目提示热线 |
| `select_single_column` | `select_single_column` | 自动选中唯一栏目 |
| `prepare_column_selection` | `prepare_column_selection` | 创建栏目选项 |
| `wait_for_column_selection` | `wait_for_column_selection` | 等用户选栏目 |
| `recommend_products` | `recommend_products` | 执行商品推荐子图 |
| `present_recommendation` | `present_recommendation` | 展示商品 |
| `wait_for_recommendation_action` | 同名方法 | 等待推荐操作 |
| `advance_product_page` | 同名方法 | 下一页 |
| `reset_for_appended_product` | 同名方法 | 追加商品时重置 |
| `complete_recommendation` | 同名方法 | 用户结束推荐 |
| `choose_procurement_mode` | 同名方法 | 进入采购方式判断 |
| `check_duplicate_self_purchase` | 同名方法 | 重复自采探针 |
| `prepare_self_purchase` | 同名方法 | 创建自采按钮 |
| `wait_for_self_purchase` | 同名方法 | 点击后跳转自采 |
| `enter_custom_purchase` | 同名方法 | 标记自定义采购 |
| `load_custom_queue` | 同名方法 | 查询排队 |
| `prepare_custom_purchase` | 同名方法 | 展示排队和按钮 |
| `wait_for_custom_purchase` | 同名方法 | 点击后跳转自定义采购 |

每一条 `add_node` 只是在服务启动时登记节点，不会调用模型或外围接口。

### 7.5 字段收集连线

```python
graph.add_edge(START, "extract_purchase_fields")
graph.add_edge("extract_purchase_fields", "prepare_missing_fields")
graph.add_conditional_edges(
    "prepare_missing_fields",
    routes.after_prepare_missing_fields,
    {"wait": "wait_for_missing_fields", "ready": "judge_ioi"},
)
graph.add_edge("wait_for_missing_fields", "prepare_missing_fields")
```

- `START` 是虚拟入口；
- 先提取字段，再检查缺失；
- 返回 `wait` 就进入表单等待；
- 返回 `ready` 就进入 IOI；
- 用户填表恢复后，再回去检查是否仍有缺失。

### 7.6 IOI 连线

```python
graph.add_conditional_edges(
    "judge_ioi",
    routes.after_ioi,
    {"ioi": "navigate_ioi", "non_ioi": "recognize_columns"},
)
graph.add_edge("navigate_ioi", END)
```

- IOI 为真：发固定导航并结束；
- IOI 为假：识别栏目；
- 未知结果不会自动当成非 IOI。

### 7.7 栏目连线

```python
graph.add_conditional_edges(
    "recognize_columns",
    routes.after_column_recognition,
    {
        "empty": "handle_no_column",
        "single": "select_single_column",
        "multiple": "prepare_column_selection",
    },
)
graph.add_edge("handle_no_column", END)
graph.add_edge("select_single_column", "recommend_products")
graph.add_edge("prepare_column_selection", "wait_for_column_selection")
graph.add_edge("wait_for_column_selection", "recommend_products")
```

- 0个栏目：热线并结束；
- 1个栏目：直接选中并推荐；
- 多个栏目：暂停让用户选；
- 恢复后直接使用保存的候选，不重新调用栏目 Agent。

### 7.8 商品连线

```python
graph.add_edge("recommend_products", "present_recommendation")
graph.add_conditional_edges(
    "present_recommendation",
    routes.after_present_recommendation,
    {
        "has_products": "wait_for_recommendation_action",
        "empty": "choose_procurement_mode",
    },
)
```

- 子图返回后先展示；
- 有商品就等待用户操作；
- 无商品直接判断采购方式。

### 7.9 四个推荐操作

```python
graph.add_conditional_edges(
    "wait_for_recommendation_action",
    routes.recommendation_action,
    {
        "next_page": "advance_product_page",
        "append_product": "reset_for_appended_product",
        "other_mode": "choose_procurement_mode",
        "end": "complete_recommendation",
    },
)
graph.add_edge("advance_product_page", "recommend_products")
graph.add_edge("reset_for_appended_product", "extract_purchase_fields")
graph.add_edge("complete_recommendation", END)
```

- 换一批：页码加1，再进入商品子图；
- 追加商品：清空当前商品数据，从字段提取重新开始；
- 其他采购方式：进入自采/自定义判断；
- 结束：场景完成。

### 7.10 采购方式连线

```python
graph.add_conditional_edges(
    "choose_procurement_mode",
    routes.procurement_mode,
    {
        "check_duplicate": "check_duplicate_self_purchase",
        "custom": "enter_custom_purchase",
    },
)
graph.add_conditional_edges(
    "check_duplicate_self_purchase",
    routes.after_duplicate_check,
    {
        "self_purchase": "prepare_self_purchase",
        "custom": "enter_custom_purchase",
    },
)
```

- 栏目允许自采才调用重复探针；
- 栏目不允许自采直接转自定义；
- 重复自采业务不允许再次自采，也转自定义；
- 不重复才展示自行采购按钮。

### 7.11 自采和自定义采购连线

```python
graph.add_edge("prepare_self_purchase", "wait_for_self_purchase")
graph.add_edge("wait_for_self_purchase", END)

graph.add_edge("enter_custom_purchase", "load_custom_queue")
graph.add_edge("load_custom_queue", "prepare_custom_purchase")
graph.add_edge("prepare_custom_purchase", "wait_for_custom_purchase")
graph.add_edge("wait_for_custom_purchase", END)
```

- 自采：先等用户点击，点击后跳转并结束；
- 所有自定义采购入口都先经过排队查询；
- 排队提示出现时场景仍未结束；
- 用户点击自定义采购后才导航并结束。

最后：

```python
return graph.compile(checkpointer=checkpointer)
```

把声明好的节点和边编译成可执行 Graph，并接入 Checkpoint。

## 8. routes.py：每个条件函数

文件：[`routes.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/routes.py)

### 8.1 缺失字段

```python
return "wait" if state.wait_request is not None else "ready"
```

有等待点就暂停，没有就继续 IOI。这是条件表达式，等价于普通 `if/else`。

### 8.2 IOI

```python
if state.is_ioi is True:
    return "ioi"
if state.is_ioi is False:
    return "non_ioi"
raise RuntimeError("IOI 路由缺少判断结果")
```

只接受明确真或假；`None` 表示流程错误，不能猜。

### 8.3 栏目数量

```python
count = len(state.column_candidates)
if count == 0:
    return "empty"
if count == 1:
    return "single"
return "multiple"
```

先数候选数量，再区分0、1和多个。

### 8.4 商品结果

```python
if state.recommendation is None:
    raise RuntimeError(...)
return "has_products" if state.recommendation.products else "empty"
```

先确认商品子图确实返回状态，再判断商品元组是否为空。

### 8.5 推荐按钮

```python
routes = {
    ActionOperation.NEXT_PAGE: "next_page",
    ActionOperation.APPEND_PRODUCT: "append_product",
    ActionOperation.OTHER_PROCUREMENT_MODE: "other_mode",
    ActionOperation.END_RECOMMENDATION: "end",
}
selected_action = state.selected_action
return routes[selected_action]
```

字典把已经校验的操作枚举映射成 Graph 分支。缺少选择或出现未知操作都会报错。

### 8.6 采购方式

```python
return (
    "check_duplicate"
    if state.selected_column.self_purchase_allowed
    else "custom"
)
```

只有选中栏目明确允许自采时才调用重复探针。

### 8.7 重复自采

```python
if state.duplicate_self_purchase is True:
    return "custom"
if state.duplicate_self_purchase is False:
    return "self_purchase"
raise RuntimeError(...)
```

重复为真转自定义，不重复转自行采购，未知不能猜。

## 9. nodes.py：每个节点逐行走查

文件：[`nodes.py`](../backend/src/procurement_assistant/orchestration/scenarios/smart_routing/nodes.py)

### 9.1 顶部导入在做什么

第1～48行只是把本文件需要的类型和接口名称导入进来，不会执行外部调用：

- `interrupt`：暂停 Graph；
- `AppSettings`：读取超时、重试和是否展示流；
- 三个 Agent Delegate：IOI、栏目、重复自采；
- `ModelDelegate`：字段提取模型；
- `QueueDelegate`：排队接口；
- 各种 Input/Result：严格校验外围调用；
- `ExecutionContext`：事件、Trace、超时和调用治理；
- `WaitRequestFactory`：创建等待点；
- 各种 Payload：生成前端事件。

### 9.2 `__init__` 保存依赖

```python
def __init__(
    self,
    *,
    settings,
    model,
    ioi,
    columns,
    duplicate_self_purchase,
    queue,
    product_graph,
    waits,
):
    self._settings = settings
    self._model = model
    self._ioi = ioi
    self._columns = columns
    self._duplicate_self_purchase = duplicate_self_purchase
    self._queue = queue
    self._product_graph = product_graph
    self._waits = waits
```

- `*` 后参数必须写名称；
- 每个参数由 Composition Root 注入；
- `self._xxx` 把依赖保存到对象；
- 节点不自行 new HTTP 客户端，测试时可以换成 Fake；
- `product_graph` 已经编译；
- `waits` 统一生成表单和按钮。

### 9.3 `extract_purchase_fields`

```python
updates: dict[str, Any] = {}
```

创建节点更新字典。节点不直接修改 State，而是返回更新。

```python
if state.region_code is None and context.page_context.region_code is not None:
    updates["region_code"] = context.page_context.region_code
```

State 没区域但页面有区域时采用页面值。模型禁止猜区域。

```python
if state.original_user_text is None:
    return updates
```

按钮进入或追加商品没有原文，不调用模型，后面用表单收集。

```python
request = PurchaseFieldExtractionInput(
    original_user_text=state.original_user_text
)
```

把原文放进严格模型输入，过长或空值会被拒绝。

内部函数：

```python
async def invoke(call_context, stream_sink):
    del stream_sink
    return await self._model.invoke_structured(
        task_id=ModelTaskId.PURCHASE_FIELD_EXTRACTION,
        input_data=request,
        output_type=PurchaseFieldExtractionResult,
        context=call_context,
    )
```

逐行：

- 定义统一治理层要调用的小函数；
- 本模型任务不展示流，所以明确忽略 `stream_sink`；
- 调用模型的结构化输出接口；
- 指定“采购字段提取”任务；
- 输入只有原文；
- 输出必须符合字段提取模型；
- 传入本次 Delegate 的 Trace、尝试次数和截止时间。

```python
extracted = await context.call_delegate(
    name="model.purchase_field_extraction",
    kind=SpanKind.MODEL,
    operation=invoke,
    settings=self._settings,
    input_data=request,
)
```

通过统一入口执行模型，自动获得超时、重试和独立 Span。

```python
for field_name in (
    "product_name",
    "purchase_purpose",
    "budget_amount",
    "currency",
):
    current_value = getattr(state, field_name)
    extracted_value = getattr(extracted, field_name)
    if current_value is None and extracted_value is not None:
        updates[field_name] = extracted_value
return updates
```

- 逐个处理可提取字段；
- `getattr` 按字段名读取对象属性；
- 只有 State 原来没有、模型明确提取到时才写入；
- 不覆盖用户先前填写的值；
- 返回字典后由 LangGraph 合并。

### 9.4 `prepare_missing_fields`

```python
del context
missing = state.missing_required_fields
if not missing:
    return {"wait_request": None}
return {"wait_request": self._waits.purchase_fields(missing)}
```

- `del context` 说明本节点不用运行工具；
- 计算缺失字段；
- 没有缺失就清掉旧等待点；
- 有缺失就只为缺失字段创建动态表单。

### 9.5 `wait_for_missing_fields`

```python
if state.wait_request is None:
    raise RuntimeError("缺失字段等待节点没有 WaitRequest")
```

走到等待节点却没有表单，是代码或 Graph 连线错误。

```python
resumed = interrupt(state.wait_request.model_dump(mode="json"))
```

把等待要求交给 LangGraph。第一次运行在此暂停，Checkpoint 保存；下一次恢复时这行返回用户
提交的值。

```python
command = GraphResumeInput.model_validate(resumed)
```

再次把恢复值校验成可信模型。

```python
if command.operation != ActionOperation.SUBMIT_FORM:
    raise InvalidUserInputError(...)
```

当前步骤只接受表单，其他按钮不能混用。

```python
return {**command.values, "wait_request": None}
```

`**` 把表单字段展开进更新字典，并清除旧等待点。随后 Graph 回到缺失字段检查。

### 9.6 `judge_ioi`

```python
request = IOIProcurementInput(
    fields=self._purchase_fields(state)
)
```

把 State 中分散字段集中成 IOI Agent 的稳定输入。

```python
async def invoke(call_context, stream_sink):
    return await self._ioi.judge(
        request,
        call_context,
        stream_sink,
    )
```

定义实际调用已有 IOI Agent 的函数。

```python
result = await context.call_delegate(
    name="agent.ioi_procurement",
    kind=SpanKind.AGENT,
    operation=invoke,
    settings=self._settings,
    expose_stream_to_ui=self._settings.ioi_expose_stream_to_ui,
    input_data=request,
)
return {"is_ioi": result.is_ioi}
```

- 通过治理层调用；
- Trace 中归类为外围 Agent；
- 是否把进度流展示给前端由配置决定；
- 最终只采用结构化 `is_ioi`，不从展示文字猜结论。

### 9.7 `navigate_ioi`

```python
del state
await context.events.custom(
    ProcurementEventName.NAVIGATION,
    NavigationPayload(target=NavigationTarget.IOI_PURCHASE),
)
return {
    "navigation_target": NavigationTarget.IOI_PURCHASE,
    "status": ScenarioStatus.COMPLETED,
}
```

- 不需要读取 State；
- 发固定导航事件，不发送任意 URL；
- 同时记录导航目标并把场景标记完成；
- Graph 下一步是 END。

### 9.8 `recognize_columns`

```python
fields = self._purchase_fields(state)
assert fields.product_name is not None
assert fields.region_code is not None
assert fields.budget_amount is not None
```

前面的缺失字段检查保证三个值存在。`assert` 是开发保护，失败说明流程代码有 bug。

```python
request = ColumnRecognitionInput(
    product_name=fields.product_name,
    region_code=fields.region_code,
    budget_amount=fields.budget_amount,
    currency=fields.currency,
)
```

构造栏目输入；币种允许 `None`。

```python
async def invoke(call_context, stream_sink):
    return await self._columns.recognize(
        request,
        call_context,
        stream_sink,
    )
```

定义栏目 Agent 调用。

```python
result = await context.call_delegate(
    name="agent.column_recognition",
    kind=SpanKind.AGENT,
    operation=invoke,
    settings=self._settings,
    expose_stream_to_ui=self._settings.column_expose_stream_to_ui,
    input_data=request,
)
return {"column_candidates": result.candidates}
```

调用一次栏目 Agent，并保存全部候选。多个栏目时，用户选择后不会再次调用。

### 9.9 `handle_no_column`

```python
del state
hotline_text = (
    self._settings.procurement_hotline_text
    or "未找到相关采购栏目，请联系采购热线。"
)
await context.events.text_message(hotline_text)
return {"status": ScenarioStatus.COMPLETED}
```

- 不需要 State；
- 优先用配置的热线文案；
- 没配置就用固定备用文案；
- 发文字并结束，不调用商品推荐。

### 9.10 `select_single_column`

```python
del context
if len(state.column_candidates) != 1:
    raise RuntimeError(...)
return {"selected_column": state.column_candidates[0]}
```

- 不需要外围工具；
- 再次确认候选数量确实为1；
- `[0]` 取得唯一候选并保存。

### 9.11 `prepare_column_selection`

```python
del context
return {
    "wait_request": self._waits.column_selection(
        state.column_candidates
    )
}
```

把这一次栏目 Agent 返回的全部候选转换成单选等待点。

### 9.12 `wait_for_column_selection`

```python
if state.wait_request is None:
    raise RuntimeError(...)
resumed = interrupt(state.wait_request.model_dump(mode="json"))
command = GraphResumeInput.model_validate(resumed)
if command.operation != ActionOperation.SELECT_OPTION:
    raise InvalidUserInputError(...)
```

- 检查等待点；
- 第一次在 `interrupt` 暂停；
- 恢复后校验命令；
- 只接受栏目选择。

```python
selected_id = command.values.get("option_id")
selected = next(
    (
        candidate
        for candidate in state.column_candidates
        if candidate.option_id == selected_id
    ),
    None,
)
```

- 取得用户选择的编号；
- 生成器逐个查看上次保存的候选；
- 找到相同 `option_id` 就返回候选；
- 全部不匹配时返回 `None`。

```python
if selected is None:
    raise InvalidUserInputError(...)
return {
    "selected_column": selected,
    "wait_request": None,
}
```

拒绝伪造候选；成功时保存选中栏目并清除等待点。

## 10. 商品推荐子图逐行走查

目录：[`product_recommendation`](../backend/src/procurement_assistant/orchestration/subgraphs/product_recommendation)

### 10.1 RecommendationState 每一项

```python
product_name: str
column_name: str
user_id: str
region_code: str
search_terms: tuple[str, ...] = ()
page: int = Field(default=1, ge=1)
page_size: int = Field(default=3, ge=1, le=20)
products: tuple[Product, ...] = ()
has_next: bool = False
result_status: Literal[
    "not_searched",
    "has_products",
    "empty",
] = "not_searched"
wait_request: WaitRequest | None = None
```

- 前四项是搜索上下文；
- `search_terms` 只在第一次由模型生成；
- `page` 当前页；
- `page_size` 默认3，可配置且限制1～20；
- `products` 当前页结果；
- `has_next` 是否还有下一页；
- `result_status` 区分未搜索、有商品、空结果；
- 状态中没有预算字段，预算不可能误传给搜索。

### 10.2 子图连线

```python
builder = StateGraph(
    RecommendationState,
    context_schema=ExecutionContext,
)
builder.add_node("extract_search_terms", extract)
builder.add_node("search_products", search)
builder.add_edge(START, "extract_search_terms")
builder.add_edge("extract_search_terms", "search_products")
builder.add_edge("search_products", END)
return builder.compile()
```

从拆搜索词开始，然后调用搜索接口，最后结束。商品展示和用户按钮仍由父 Graph 管理。

### 10.3 `extract_search_terms`

```python
if state.search_terms:
    return {}
```

已有搜索词时返回空更新。换一批不会再次调用模型。

```python
request = ProductSearchTermsInput(
    product_name=state.product_name,
    column_name=state.column_name,
)
```

模型输入只有商品名和栏目名，没有预算。

内部 `invoke` 调用：

```python
self._model.invoke_structured(
    task_id=ModelTaskId.PRODUCT_SEARCH_TERMS,
    input_data=request,
    output_type=SearchTermsResult,
    context=call_context,
)
```

要求模型返回严格搜索词数组。

```python
result = await context.call_delegate(...)
return {"search_terms": result.search_terms}
```

通过统一治理层调用，并把搜索词保存到子图 State。

### 10.4 `search_products`

```python
request = ProductSearchInput(
    search_terms=state.search_terms,
    column_name=state.column_name,
    user_id=state.user_id,
    region_code=state.region_code,
    page=state.page,
    page_size=state.page_size,
)
```

逐项组装搜索接口参数。仍然没有预算。

```python
async def invoke(call_context, stream_sink):
    del stream_sink
    return await self._search.search(
        request,
        call_context,
    )
```

定义实际搜索调用；当前搜索接口不向页面转发内部流。

```python
result = await context.call_delegate(
    name="service.product_search",
    kind=SpanKind.SERVICE,
    operation=invoke,
    settings=self._settings,
    input_data=request,
)
```

通过统一服务 Delegate 调用，自动记录超时和耗时。

```python
return {
    "products": result.products,
    "has_next": result.has_next,
    "result_status": (
        "has_products" if result.products else "empty"
    ),
}
```

原样保留搜索接口已经排序好的商品，不在 Agent 中重新打分。

## 11. 父 Graph 怎样调用商品子图

### 11.1 `recommend_products`

```python
if (
    state.selected_column is None
    or state.product_name is None
    or state.region_code is None
):
    raise RuntimeError(...)
```

确保子图的三个必要业务字段存在。

```python
recommendation = (
    state.recommendation
    or RecommendationState(
        product_name=state.product_name,
        column_name=state.selected_column.column_name,
        user_id=context.user_id,
        region_code=state.region_code,
        page_size=self._settings.product_page_size,
    )
)
```

- 第一次进入时创建子图 State；
- 换一批时 `state.recommendation` 已存在，直接复用；
- 页大小来自配置；
- 没传预算。

```python
async with context.trace.start_span(...) as span:
    result = await self._product_graph.ainvoke(
        recommendation,
        context=context,
    )
    span.set_output(result)
```

建立商品子图总耗时，然后异步执行小 Graph。

```python
return {
    "recommendation": RecommendationState.model_validate(
        result
    )
}
```

子图结果再次通过 Pydantic，再放入主 State。

### 11.2 `present_recommendation`

```python
recommendation = self._require_recommendation(state)
if not recommendation.products:
    await context.events.text_message(
        "没有找到符合条件的商品。"
    )
    return {"wait_request": None}
```

没有商品时发固定文字，不生成商品按钮，条件边直接进入采购方式判断。

有商品时：

```python
await context.events.custom(
    ProcurementEventName.PRODUCTS,
    ProductsPayload(
        page=recommendation.page,
        page_size=recommendation.page_size,
        has_next=recommendation.has_next,
        products=tuple(
            ProductView.from_domain(product)
            for product in recommendation.products
        ),
    ),
)
```

- 事件名表示商品列表；
- 传页码、页大小和下一页标志；
- 每个领域商品转换成安全前端字段；
- `tuple(...)` 固定当前列表；
- 前端商品卡中的“加购”由前端处理，不调用 Agent。

```python
return {
    "wait_request": self._waits.recommendation_actions(
        has_next=recommendation.has_next
    )
}
```

生成“换一批、追加商品、其他采购方式、结束推荐”等待点。没有下一页时不生成“换一批”。

### 11.3 `wait_for_recommendation_action`

```python
resumed = interrupt(...)
command = GraphResumeInput.model_validate(resumed)
allowed = {
    ActionOperation.NEXT_PAGE,
    ActionOperation.APPEND_PRODUCT,
    ActionOperation.OTHER_PROCUREMENT_MODE,
    ActionOperation.END_RECOMMENDATION,
}
if command.operation not in allowed:
    raise InvalidUserInputError(...)
return {
    "selected_action": command.operation,
    "wait_request": None,
}
```

暂停等待操作；恢复后只接受四种白名单操作，并把选择交给路由。

### 11.4 “换一批”每一项更新

```python
recommendation.model_copy(
    update={
        "page": recommendation.page + 1,
        "products": (),
        "has_next": False,
        "result_status": "not_searched",
        "wait_request": None,
    }
)
```

- 复制状态而不是原地改；
- 页码加1；
- 清掉上一页商品；
- 下一页是否还有更多先设为未知的 `False`；
- 标记还没搜索；
- 清旧等待点；
- 保留 `search_terms`，所以子图跳过模型拆词。

### 11.5 “追加其他商品”每一项更新

`reset_for_appended_product` 返回：

```python
{
    "item_sequence": state.item_sequence + 1,
    "original_user_text": None,
    "product_name": None,
    "purchase_purpose": None,
    "budget_amount": None,
    "currency": None,
    "is_ioi": None,
    "column_candidates": (),
    "selected_column": None,
    "recommendation": None,
    "duplicate_self_purchase": None,
    "entered_custom_purchase": False,
    "queue_count": None,
    "navigation_target": None,
    "selected_action": None,
}
```

逐项作用：

- 商品序号加1；
- 没有新的自然语言，后续展示表单；
- 清空当前商品、用途、预算和币种；
- 强制新商品重新经过 IOI；
- 清空栏目和商品推荐；
- 清空采购方式判断、排队和导航；
- 保留 `region_code`，因为仍是同一页面区域；
- 保持同一个场景实例，不启动另一场景。

### 11.6 “结束本次推荐”

```python
return {
    "selected_action": None,
    "status": ScenarioStatus.COMPLETED,
}
```

清掉操作并结束场景，不跳转页面。

## 12. 自采和自定义采购逐行走查

### 12.1 `choose_procurement_mode`

```python
del state, context
return {"selected_action": None}
```

本节点只清掉上一阶段操作。下一条条件边读取栏目中的 `self_purchase_allowed`。

### 12.2 `check_duplicate_self_purchase`

```python
if (
    state.product_name is None
    or state.selected_column is None
):
    raise RuntimeError(...)
```

确保探针需要的商品和栏目存在。

```python
request = DuplicateSelfPurchaseInput(
    product_name=state.product_name,
    column_name=state.selected_column.column_name,
    user_id=context.user_id,
)
```

探针输入是商品名、栏目名和当前用户。

```python
async def invoke(call_context, stream_sink):
    return await self._duplicate_self_purchase.check(
        request,
        call_context,
        stream_sink,
    )
```

定义实际外围 Agent 调用。

```python
result = await context.call_delegate(
    name="agent.duplicate_self_purchase",
    kind=SpanKind.AGENT,
    operation=invoke,
    settings=self._settings,
    expose_stream_to_ui=(
        self._settings
        .duplicate_self_purchase_expose_stream_to_ui
    ),
    input_data=request,
)
return {
    "duplicate_self_purchase": result.is_duplicate
}
```

通过统一治理层调用，并只保存结构化布尔结果。

### 12.3 不重复时准备自行采购按钮

```python
return {
    "wait_request": self._waits.single_navigation_action(
        ActionOperation.GO_SELF_PURCHASE,
        title="该栏目允许自行采购",
        label="自行采购",
    )
}
```

这里只显示按钮，不立即跳转。

### 12.4 点击自行采购后

```python
resumed = interrupt(...)
command = GraphResumeInput.model_validate(resumed)
if command.operation != ActionOperation.GO_SELF_PURCHASE:
    raise InvalidUserInputError(...)
```

暂停、恢复并验证操作。

```python
await context.events.custom(
    ProcurementEventName.NAVIGATION,
    NavigationPayload(
        target=NavigationTarget.SELF_PURCHASE
    ),
)
return {
    "wait_request": None,
    "navigation_target": NavigationTarget.SELF_PURCHASE,
    "status": ScenarioStatus.COMPLETED,
}
```

点击后才发固定自采页面导航，并结束场景。

### 12.5 统一进入自定义采购

```python
return {
    "entered_custom_purchase": True,
    "queue_count": None,
}
```

无论栏目不允许自采还是发生重复自采，都先设置同一标记并清空旧排队数量。

### 12.6 查询排队

```python
if not state.entered_custom_purchase:
    raise RuntimeError(...)
request = QueueInput(user_id=context.user_id)
```

保护 Graph 连线，确保只有进入自定义采购后才能查；接口输入只需要用户编号。

```python
async def invoke(call_context, stream_sink):
    del stream_sink
    return await self._queue.get_queue(
        request,
        call_context,
    )
```

定义排队服务调用，不展示内部流。

```python
try:
    result = await context.call_delegate(...)
    return {"queue_count": result.count}
except ProcurementAssistantError:
    return {"queue_count": None}
```

- 正常时保存外部返回数量；
- 排队提示不是资格判断；
- 调用失败不能阻止用户办事；
- 失败仍保留 Trace，但继续显示自定义采购按钮。

### 12.7 展示排队和按钮

```python
if (
    state.queue_count is not None
    and state.queue_count > 0
):
    await context.events.custom(
        ProcurementEventName.QUEUE,
        QueuePayload.from_count(state.queue_count),
    )
```

只有数量大于0时展示固定文案；没有数量或数量为0时不显示排队信息。

```python
return {
    "wait_request": self._waits.single_navigation_action(
        ActionOperation.GO_CUSTOM_PURCHASE,
        title="你可以进入自定义采购",
        label="自定义采购",
    )
}
```

签发自定义采购按钮。此时场景仍是等待，不提前结束。

### 12.8 点击自定义采购后

`wait_for_custom_purchase` 与自行采购结构相同：

1. 检查等待点存在；
2. `interrupt` 暂停或取得恢复命令；
3. 只允许 `GO_CUSTOM_PURCHASE`；
4. 发固定 `CUSTOM_PURCHASE` 导航；
5. 清等待点；
6. 状态改为完成；
7. Graph 到 END。

## 13. 文件末尾两个辅助方法

### 13.1 `_purchase_fields`

```python
@staticmethod
def _purchase_fields(state):
    return PurchaseFields(
        product_name=state.product_name,
        purchase_purpose=state.purchase_purpose,
        budget_amount=state.budget_amount,
        currency=state.currency,
        region_code=state.region_code,
    )
```

- `@staticmethod` 表示不需要 `self`；
- 把 State 中分散字段组装成统一领域模型；
- Pydantic 再次校验数据；
- IOI、栏目等 Delegate 复用同一含义。

### 13.2 `_require_recommendation`

```python
@staticmethod
def _require_recommendation(state):
    if state.recommendation is None:
        raise RuntimeError(...)
    return state.recommendation
```

应该已有推荐结果却没有时立即报开发错误；否则返回结果，减少各节点重复判断。

## 14. WaitRequestFactory 怎样创建等待点

文件：[`wait_factory.py`](../backend/src/procurement_assistant/orchestration/wait_factory.py)

### 14.1 创建和过期时间

```python
created_at = self._clock.now()
return created_at, created_at + self._ttl
```

取得统一创建时间，并加上配置的24小时得到过期时间。

### 14.2 创建一次性 Action

```python
return PendingActionDefinition(
    action_id=self._ids.new("action"),
    kind=operation,
    input_schema_id=schema_id,
    label=label,
    style=style,
    payload=payload or {},
)
```

- 生成不可预测 Action ID；
- 保存操作枚举；
- 指定静态输入校验模型；
- 保存按钮文案和样式；
- payload 保存栏目允许候选等服务端数据。

### 14.3 采购字段表单

`purchase_fields()` 先定义商品名称、用途、预算和区域四种字段，再使用：

```python
fields=tuple(
    field_definitions[field]
    for field in missing_fields
)
```

只选择当前真正缺失的字段，避免重复追问。

### 14.4 栏目选择

`column_selection()`：

- 把全部候选 ID 放入 Action payload，入口就能拒绝伪造 ID；
- 把栏目名作为 label；
- 把品类名作为 description；
- 只允许单选。

### 14.5 推荐操作

`recommendation_actions()`：

- `has_next=True` 才生成“换一批”；
- 总是生成“追加其他商品”；
- 总是生成“其他采购方式”；
- 总是生成“结束本次推荐”。

### 14.6 单导航按钮

`single_navigation_action()` 复用同一结构创建“自行采购”或“自定义采购”按钮。

## 15. 用户下一次请求如何恢复

第一次执行 `interrupt` 后：

1. LangGraph 保存 State Checkpoint；
2. GraphRunner 保存 WaitRequest 和一次性 Action；
3. GraphRunner 把表单、选项或按钮发给前端；
4. 当前场景状态改为 `WAITING`；
5. 当前 HTTP Run 发出 `RUN_FINISHED`。

用户点击后：

```text
前端提交 action_id / values
    ↓
run_agent
    ↓
AgentApplication.admit
    ├─ 从数据库读取 Action
    ├─ 按 input_schema_id 校验值
    ├─ 校验栏目 option_id 属于原候选
    └─ 短事务中消费一次性 Action
    ↓
AgentApplication._dispatch
    ↓
GraphRunner.resume
    ↓
Command(resume=GraphResumeInput(...))
    ↓
LangGraph 从 interrupt 位置继续
```

新的点击产生新 `run_id`，但 `thread_id` 和 `scenario_instance_id` 不变，因此恢复的是同一个
场景而不是新建场景。

## 16. Graph 结果如何回到用户

Graph 到达 END 或 interrupt 后，返回 `GraphExecutionResult`。随后：

1. `AgentApplication` 保存本轮助手文字和 UI 块；
2. 数据库把当前 Run 标记成功并释放会话租约；
3. 发出 `RUN_FINISHED`；
4. `agent.py` 从请求队列读取事件；
5. `encode_sse_event` 编成 `data: {...}\n\n`；
6. 浏览器 `client.ts` 解析每一帧；
7. `eventReducer.ts` 更新页面消息、栏目、商品、按钮、排队或导航；
8. React 自动重新渲染。

要特别区分：

- `RUN_FINISHED`：本次 HTTP Run 结束；
- `ScenarioStatus.WAITING`：场景等待下一次用户输入；
- `ScenarioStatus.COMPLETED`：整个场景已经结束。

## 17. 三个完整例子

### 17.1 IOI 采购

1. 提取字段；
2. 字段齐全；
3. IOI Agent 返回 `True`；
4. 条件路由选择 `navigate_ioi`；
5. 发 IOI 导航事件；
6. State 标记完成；
7. Graph 到 END；
8. 前端跳转 IOI 页面。

### 17.2 多栏目后换一批

1. 栏目 Agent 返回多个候选；
2. 保存候选并 `interrupt`；
3. 用户选择一个 `option_id`；
4. 在旧候选中精确匹配，不再调栏目 Agent；
5. 子图第一次调用模型拆词；
6. 搜索第1页并展示；
7. 用户点击“换一批”；
8. 页码加1，搜索词保留；
9. 子图跳过模型，只搜索第2页；
10. 前端展示新商品。

### 17.3 无商品、重复自采、进入自定义采购

1. 搜索返回空；
2. 显示“没有找到符合条件的商品”；
3. 栏目允许自采，调用重复探针；
4. 探针返回重复；
5. 路由转自定义采购；
6. 调排队接口；
7. 数量大于0时显示固定排队文案；
8. 显示自定义采购按钮；
9. 用户点击后才发导航；
10. 场景完成。

## 18. 推荐断点顺序

1. `api/agent.py → run_agent`：看 API 输入；
2. `application.py → _dispatch`：看输入类型；
3. `graph_runner.py → start`：看场景编号和初始 State；
4. `smart_routing/graph.py → _bind`：看当前节点；
5. `nodes.py → extract_purchase_fields`：看节点输入和更新；
6. `routes.py`：看分支字符串；
7. 各 Delegate 节点：看严格输入和结构化结果；
8. `protocol/emitter.py → _publish`：看 UI 事件；
9. `api/agent.py → stream_events`：看 SSE；
10. `frontend/eventReducer.ts`：看页面状态。

每次停在断点时只问两个问题：

1. 当前 State 已经知道什么？
2. 这一行是在更新 State，还是在向前端发送 Event？

能回答这两个问题，就能顺着代码看懂整个智能分流。
