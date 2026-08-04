"""商品推荐 Subgraph 的确定性节点。"""

from typing import Any

from procurement_assistant.config import AppSettings
from procurement_assistant.delegates.common.call_context import DelegateCallContext
from procurement_assistant.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.delegates.model.interface import ModelDelegate, ModelTaskId
from procurement_assistant.delegates.services.product_search import ProductSearchDelegate
from procurement_assistant.domain.procurement import (
    ProductSearchInput,
    ProductSearchResult,
    ProductSearchTermsInput,
    SearchTermsResult,
)
from procurement_assistant.observability.models import SpanKind
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.orchestration.subgraphs.product_recommendation.state import (
    RecommendationState,
)


class ProductRecommendationNodes:
    """商品推荐节点集合。

    依赖通过构造函数显式传入。换一批时 ``search_terms`` 已存在，拆词节点直接跳过，
    从实现上保证模型只在一个商品的首次推荐中调用一次。
    """

    def __init__(
        self,
        *,
        model: ModelDelegate,
        search: ProductSearchDelegate,
        settings: AppSettings,
    ) -> None:
        self._model = model
        self._search = search
        self._settings = settings

    async def extract_search_terms(
        self, state: RecommendationState, context: ExecutionContext
    ) -> dict[str, Any]:
        """只根据商品名称和栏目名称拆解有效搜索词。"""

        if state.search_terms:
            return {}

        request = ProductSearchTermsInput(
            product_name=state.product_name,
            column_name=state.column_name,
        )

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> SearchTermsResult:
            del stream_sink
            return await self._model.invoke_structured(
                task_id=ModelTaskId.PRODUCT_SEARCH_TERMS,
                input_data=request,
                output_type=SearchTermsResult,
                context=call_context,
            )

        result = await context.call_delegate(
            name="model.product_search_terms",
            kind=SpanKind.MODEL,
            operation=invoke,
            settings=self._settings,
            input_data=request,
        )
        return {"search_terms": result.search_terms}

    async def search_products(
        self, state: RecommendationState, context: ExecutionContext
    ) -> dict[str, Any]:
        """调用分页搜索接口并原样保留接口排序。"""

        request = ProductSearchInput(
            search_terms=state.search_terms,
            column_name=state.column_name,
            user_id=state.user_id,
            region_code=state.region_code,
            page=state.page,
            page_size=state.page_size,
        )

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> ProductSearchResult:
            del stream_sink
            return await self._search.search(request, call_context)

        result = await context.call_delegate(
            name="service.product_search",
            kind=SpanKind.SERVICE,
            operation=invoke,
            settings=self._settings,
            input_data=request,
        )
        return {
            "products": result.products,
            "has_next": result.has_next,
            "result_status": "has_products" if result.products else "empty",
        }
