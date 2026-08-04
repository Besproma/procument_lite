"""知识推荐 LangGraph 的显式节点与边。"""

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from procurement_assistant.observability.models import SpanKind
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.orchestration.scenarios.knowledge import routes
from procurement_assistant.orchestration.scenarios.knowledge.nodes import KnowledgeNodes
from procurement_assistant.orchestration.scenarios.knowledge.state import KnowledgeState

NodeMethod = Callable[[KnowledgeState, ExecutionContext], Awaitable[dict[str, Any]]]


def _bind(method: NodeMethod) -> Callable[..., Awaitable[dict[str, Any]]]:
    """把纯节点签名适配为 LangGraph Runtime 签名。"""

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
    """构建“收集 key -> 精确匹配 -> 原样响应”的确定性 Graph。"""

    graph = StateGraph(KnowledgeState, context_schema=ExecutionContext)
    graph.add_node("prepare_query", _bind(nodes.prepare_query))
    graph.add_node("wait_for_query", _bind(nodes.wait_for_query))
    graph.add_node("exact_match", _bind(nodes.exact_match))
    graph.add_node("respond", _bind(nodes.respond))

    graph.add_edge(START, "prepare_query")
    graph.add_conditional_edges(
        "prepare_query",
        routes.after_prepare_query,
        {"wait": "wait_for_query", "match": "exact_match"},
    )
    graph.add_edge("wait_for_query", "exact_match")
    graph.add_edge("exact_match", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer)
