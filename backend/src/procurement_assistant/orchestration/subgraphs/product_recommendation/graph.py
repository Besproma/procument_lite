"""商品推荐 LangGraph Subgraph 构建。"""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from procurement_assistant.observability.models import SpanKind
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.orchestration.subgraphs.product_recommendation.nodes import (
    ProductRecommendationNodes,
)
from procurement_assistant.orchestration.subgraphs.product_recommendation.state import (
    RecommendationState,
)


def build_product_recommendation_graph(nodes: ProductRecommendationNodes) -> Any:
    """显式构建“拆词 -> 搜索”的内部 Subgraph。

    Subgraph 不包含用户等待；商品展示和操作等待由智能分流父 Graph 管理。这样内部图
    专注搜索，而父 Graph 可以把“换一批、追加商品、其他方式、结束”放在同一等待点。
    """

    builder = StateGraph(RecommendationState, context_schema=ExecutionContext)

    async def extract(
        state: RecommendationState,
        runtime: Runtime[ExecutionContext],
    ) -> dict[str, Any]:
        async with runtime.context.trace.start_span(
            kind=SpanKind.NODE,
            name="node.product_recommendation.extract_search_terms",
            target="extract_search_terms",
            input_json=state,
        ) as span:
            result = await nodes.extract_search_terms(state, runtime.context)
            span.set_output(result)
            return result

    async def search(
        state: RecommendationState,
        runtime: Runtime[ExecutionContext],
    ) -> dict[str, Any]:
        async with runtime.context.trace.start_span(
            kind=SpanKind.NODE,
            name="node.product_recommendation.search_products",
            target="search_products",
            input_json=state,
        ) as span:
            result = await nodes.search_products(state, runtime.context)
            span.set_output(result)
            return result

    builder.add_node("extract_search_terms", extract)
    builder.add_node("search_products", search)
    builder.add_edge(START, "extract_search_terms")
    builder.add_edge("extract_search_terms", "search_products")
    builder.add_edge("search_products", END)
    return builder.compile()
