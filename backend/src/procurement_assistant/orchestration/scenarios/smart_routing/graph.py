"""智能分流 LangGraph 的显式节点与边。"""

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from procurement_assistant.observability.models import SpanKind
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.orchestration.scenarios.smart_routing import routes
from procurement_assistant.orchestration.scenarios.smart_routing.nodes import SmartRoutingNodes
from procurement_assistant.orchestration.scenarios.smart_routing.state import SmartRoutingState

NodeMethod = Callable[[SmartRoutingState, ExecutionContext], Awaitable[dict[str, Any]]]


def _bind(method: NodeMethod) -> Callable[..., Awaitable[dict[str, Any]]]:
    """给普通业务节点包一层 LangGraph 需要的函数签名和耗时记录。

    本函数写在 build_smart_routing_graph 前面只是为了先定义、后使用。导入模块时 Python
    只创建函数对象，不执行本函数体；真正调用发生在下面每个 add_node 的参数中。
    """

    async def wrapped(
        state: SmartRoutingState,
        runtime: Runtime[ExecutionContext],
    ) -> dict[str, Any]:
        # wrapped 是 LangGraph 实际调用的函数；method 才是 nodes.py 中容易阅读的业务
        # 方法。每个节点单独计时，才能区分“Graph 总体慢”究竟是字段提取、某个外围调用，
        # 还是纯业务节点耗时。节点输出仍由 LangGraph 合并，Trace 只读取副本。
        async with runtime.context.trace.start_span(
            kind=SpanKind.NODE,
            name=f"node.smart_routing.{method.__name__}",
            target=method.__name__,
            input_json=state,
        ) as span:
            result = await method(state, runtime.context)
            span.set_output(result)
            return result

    return wrapped


def build_smart_routing_graph(nodes: SmartRoutingNodes, *, checkpointer: Any) -> Any:
    """构建并编译智能分流 Graph。

    图结构完全由代码显式声明。部署配置和数据库不能增加节点或修改边；关键采购结论只
    能沿下列确定性路径发生。
    """

    # 这是构建函数运行后的第一个实际步骤：先创建 Graph，再在后面的 add_node 参数中
    # 逐次调用 _bind。源码里 _bind 的定义位置更靠前，不表示它会先于本行执行。
    # 可以把 StateGraph 想成一张“带共享记事本的流程图”：
    # - SmartRoutingState 是流程记事本，保存商品名、用途、栏目等业务状态；
    # - ExecutionContext 是运行工具包，提供事件、Trace 和调用外围服务的能力。
    graph = StateGraph(SmartRoutingState, context_schema=ExecutionContext)

    # Python 会先计算函数参数，所以每一行的执行细分为：先调用 _bind 得到 wrapped，
    # 再调用 graph.add_node 注册 wrapped。此时仍没有执行 wrapped 内的业务节点。
    graph.add_node("extract_purchase_fields", _bind(nodes.extract_purchase_fields))
    graph.add_node("prepare_missing_fields", _bind(nodes.prepare_missing_fields))
    graph.add_node("wait_for_missing_fields", _bind(nodes.wait_for_missing_fields))
    graph.add_node("judge_ioi", _bind(nodes.judge_ioi))
    graph.add_node("navigate_ioi", _bind(nodes.navigate_ioi))
    graph.add_node("recognize_columns", _bind(nodes.recognize_columns))
    graph.add_node("handle_no_column", _bind(nodes.handle_no_column))
    graph.add_node("select_single_column", _bind(nodes.select_single_column))
    graph.add_node("prepare_column_selection", _bind(nodes.prepare_column_selection))
    graph.add_node("wait_for_column_selection", _bind(nodes.wait_for_column_selection))
    graph.add_node("recommend_products", _bind(nodes.recommend_products))
    graph.add_node("present_recommendation", _bind(nodes.present_recommendation))
    graph.add_node(
        "wait_for_recommendation_action",
        _bind(nodes.wait_for_recommendation_action),
    )
    graph.add_node("advance_product_page", _bind(nodes.advance_product_page))
    graph.add_node("reset_for_appended_product", _bind(nodes.reset_for_appended_product))
    graph.add_node("complete_recommendation", _bind(nodes.complete_recommendation))
    graph.add_node("choose_procurement_mode", _bind(nodes.choose_procurement_mode))
    graph.add_node(
        "check_duplicate_self_purchase",
        _bind(nodes.check_duplicate_self_purchase),
    )
    graph.add_node("prepare_self_purchase", _bind(nodes.prepare_self_purchase))
    graph.add_node("wait_for_self_purchase", _bind(nodes.wait_for_self_purchase))
    graph.add_node("enter_custom_purchase", _bind(nodes.enter_custom_purchase))
    graph.add_node("load_custom_queue", _bind(nodes.load_custom_queue))
    graph.add_node("prepare_custom_purchase", _bind(nodes.prepare_custom_purchase))
    graph.add_node("wait_for_custom_purchase", _bind(nodes.wait_for_custom_purchase))

    # add_edge 表示固定的下一步；add_conditional_edges 表示根据 routes.py 的返回值选择
    # 分支。START 是流程入口，END 是本次场景结束。顺着这些边从上往下读，就能看到完整
    # 智能分流顺序。
    graph.add_edge(START, "extract_purchase_fields")
    graph.add_edge("extract_purchase_fields", "prepare_missing_fields")
    graph.add_conditional_edges(
        "prepare_missing_fields",
        routes.after_prepare_missing_fields,
        {"wait": "wait_for_missing_fields", "ready": "judge_ioi"},
    )
    graph.add_edge("wait_for_missing_fields", "prepare_missing_fields")

    graph.add_conditional_edges(
        "judge_ioi",
        routes.after_ioi,
        {"ioi": "navigate_ioi", "non_ioi": "recognize_columns"},
    )
    graph.add_edge("navigate_ioi", END)

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

    graph.add_edge("recommend_products", "present_recommendation")
    graph.add_conditional_edges(
        "present_recommendation",
        routes.after_present_recommendation,
        {
            "has_products": "wait_for_recommendation_action",
            "empty": "choose_procurement_mode",
        },
    )
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
    graph.add_edge("prepare_self_purchase", "wait_for_self_purchase")
    graph.add_edge("wait_for_self_purchase", END)

    # 两种自定义采购来源汇入同一节点，强制它们都调用 Queue。不得从分支直接连到
    # prepare_custom_purchase，否则会违反“只要进入自定义采购都查询排队信息”。
    graph.add_edge("enter_custom_purchase", "load_custom_queue")
    graph.add_edge("load_custom_queue", "prepare_custom_purchase")
    graph.add_edge("prepare_custom_purchase", "wait_for_custom_purchase")
    graph.add_edge("wait_for_custom_purchase", END)

    # compile 把上面声明的节点和边检查并组装成可执行 Graph。checkpointer 让流程能在
    # interrupt 时保存状态，并在用户下一次提交按钮或表单后继续。
    return graph.compile(checkpointer=checkpointer)
