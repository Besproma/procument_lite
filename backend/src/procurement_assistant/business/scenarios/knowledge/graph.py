"""知识推荐 LangGraph 的显式节点与边。"""

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from procurement_assistant.business.scenarios.knowledge import routes
from procurement_assistant.business.scenarios.knowledge.nodes import KnowledgeNodes
from procurement_assistant.business.scenarios.knowledge.state import KnowledgeState
from procurement_assistant.core.observability.models import SpanKind
from procurement_assistant.core.orchestration.runtime import ExecutionContext

NodeMethod = Callable[[KnowledgeState, ExecutionContext], Awaitable[dict[str, Any]]]


def _bind(method: NodeMethod) -> Callable[..., Awaitable[dict[str, Any]]]:
    """给普通节点包上 LangGraph 运行参数，并为每个节点记录独立耗时。"""

    async def wrapped(
        state: KnowledgeState,
        runtime: Runtime[ExecutionContext],
    ) -> dict[str, Any]:
        async with runtime.context.trace.start_span(
            kind=SpanKind.NODE,
            name=f"node.knowledge.{method.__name__}",
            target=method.__name__,
            input_json=state,
        ) as span:
            result = await method(state, runtime.context)
            span.set_output(result)
            return result

    return wrapped


def build_knowledge_graph(nodes: KnowledgeNodes, *, checkpointer: Any) -> Any:
    """声明“收集 key → 精确匹配 → 原样响应”的固定流程图。"""

    # StateGraph 在应用启动时构建一次。add_node 注册步骤，add_edge 声明步骤之间的连线；
    # 它们只描述流程，不会在这里调用知识接口。
    graph = StateGraph(KnowledgeState, context_schema=ExecutionContext)
    graph.add_node("prepare_query", _bind(nodes.prepare_query))
    graph.add_node("wait_for_query", _bind(nodes.wait_for_query))
    graph.add_node("exact_match", _bind(nodes.exact_match))
    graph.add_node("respond", _bind(nodes.respond))

    # 从 START 顺着边阅读：有查询词就去 exact_match；没有查询词就先 interrupt，等待
    # 用户填写表单，恢复后再匹配；最后 respond 产生文字事件并走到 END。
    graph.add_edge(START, "prepare_query")
    graph.add_conditional_edges(
        "prepare_query",
        routes.after_prepare_query,
        {"wait": "wait_for_query", "match": "exact_match"},
    )
    graph.add_edge("wait_for_query", "exact_match")
    graph.add_edge("exact_match", "respond")
    graph.add_edge("respond", END)
    # checkpointer 负责持久化 interrupt 时的流程状态，使下一次请求可以从等待点恢复。
    return graph.compile(checkpointer=checkpointer)
