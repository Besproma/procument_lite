"""智能分流 Scenario Graph 的业务节点。"""

from typing import Any

from langgraph.types import interrupt

from procurement_assistant.business.config.settings import BusinessSettings
from procurement_assistant.business.delegates.agents.column_recognition import (
    ColumnRecognitionDelegate,
)
from procurement_assistant.business.delegates.agents.duplicate_self_purchase import (
    DuplicateSelfPurchaseDelegate,
)
from procurement_assistant.business.delegates.agents.ioi import IOIProcurementDelegate
from procurement_assistant.business.delegates.services.queue import QueueDelegate
from procurement_assistant.business.domain.procurement import (
    ColumnRecognitionInput,
    ColumnRecognitionResult,
    DuplicateSelfPurchaseInput,
    DuplicateSelfPurchaseResult,
    IOIProcurementInput,
    IOIProcurementResult,
    NavigationTarget,
    PurchaseFieldExtractionInput,
    PurchaseFieldExtractionResult,
    PurchaseFields,
    QueueInput,
    QueueResult,
)
from procurement_assistant.business.interaction.operations import BusinessActionOperation
from procurement_assistant.business.interaction.wait_factory import BusinessWaitRequestFactory
from procurement_assistant.business.protocol.events import (
    BusinessEventName,
    NavigationPayload,
    ProductsPayload,
    ProductView,
    QueuePayload,
)
from procurement_assistant.business.registry.model_tasks import BusinessModelTask
from procurement_assistant.business.scenarios.smart_routing.state import SmartRoutingState
from procurement_assistant.business.scenarios.subgraphs.product_recommendation.state import (
    RecommendationState,
)
from procurement_assistant.core.delegates.common.call_context import DelegateCallContext
from procurement_assistant.core.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.core.delegates.model.interface import ModelDelegate
from procurement_assistant.core.domain.errors import (
    InvalidUserInputError,
    ProcurementAssistantError,
)
from procurement_assistant.core.domain.lifecycle import ScenarioStatus
from procurement_assistant.core.observability.models import SpanKind
from procurement_assistant.core.orchestration.resume import GraphResumeInput
from procurement_assistant.core.orchestration.runtime import ExecutionContext


class SmartRoutingNodes:
    """智能分流的全部节点依赖和实现。

    类只保存构造期注入的 Delegate 与已编译商品 Subgraph。每个方法只完成一个步骤，
    路由条件放在独立 ``routes.py``，从而可以直接阅读 Graph 文件理解完整业务顺序。
    """

    def __init__(
        self,
        *,
        settings: BusinessSettings,
        model: ModelDelegate,
        ioi: IOIProcurementDelegate,
        columns: ColumnRecognitionDelegate,
        duplicate_self_purchase: DuplicateSelfPurchaseDelegate,
        queue: QueueDelegate,
        product_graph: Any,
        waits: BusinessWaitRequestFactory,
    ) -> None:
        self._settings = settings
        self._model = model
        self._ioi = ioi
        self._columns = columns
        self._duplicate_self_purchase = duplicate_self_purchase
        self._queue = queue
        self._product_graph = product_graph
        self._waits = waits

    async def extract_purchase_fields(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """从自然语言提取可靠字段，并采用页面区域上下文。

        按钮进入或“追加其他商品”没有原始文字时不调用模型，直接进入结构化表单。页面
        ``regionCode`` 优先于模型，因为字段提取 Prompt 明确禁止模型猜测区域。
        """

        updates: dict[str, Any] = {}
        if state.region_code is None and context.page_context.region_code is not None:
            updates["region_code"] = context.page_context.region_code

        if state.original_user_text is None:
            return updates

        request = PurchaseFieldExtractionInput(original_user_text=state.original_user_text)

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> PurchaseFieldExtractionResult:
            del stream_sink
            return await self._model.invoke_structured(
                task_id=BusinessModelTask.PURCHASE_FIELD_EXTRACTION,
                input_data=request,
                output_type=PurchaseFieldExtractionResult,
                context=call_context,
            )

        extracted = await context.call_delegate(
            name="model.purchase_field_extraction",
            kind=SpanKind.MODEL,
            operation=invoke,
            input_data=request,
        )
        for field_name in ("product_name", "purchase_purpose", "budget_amount", "currency"):
            current_value = getattr(state, field_name)
            extracted_value = getattr(extracted, field_name)
            if current_value is None and extracted_value is not None:
                updates[field_name] = extracted_value
        return updates

    async def prepare_missing_fields(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """字段不齐时准备 Form WaitRequest；字段齐全时清除旧等待点。"""

        del context
        missing = state.missing_required_fields
        if not missing:
            return {"wait_request": None}
        return {"wait_request": self._waits.purchase_fields(missing)}

    async def wait_for_missing_fields(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """暂停并合并用户补充字段。

        ``wait_request`` 已由前一节点写入 Checkpoint。恢复时节点重新执行，但 ID 不会重新
        生成；interrupt 返回的是 Graph Runner 已按 Action Schema 校验过的可信值。
        """

        del context
        if state.wait_request is None:
            raise RuntimeError("缺失字段等待节点没有 WaitRequest")
        resumed = interrupt(state.wait_request.model_dump(mode="json"))
        command = GraphResumeInput.model_validate(resumed)
        if command.operation != BusinessActionOperation.SUBMIT_FORM:
            raise InvalidUserInputError("当前步骤只接受采购信息表单")
        return {**command.values, "wait_request": None}

    async def judge_ioi(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """调用 IOI Agent；关键结果只能来自完整结构化 final_result。"""

        request = IOIProcurementInput(fields=self._purchase_fields(state))

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> IOIProcurementResult:
            return await self._ioi.judge(request, call_context, stream_sink)

        result = await context.call_delegate(
            name="agent.ioi_procurement",
            kind=SpanKind.AGENT,
            operation=invoke,
            expose_stream_to_ui=self._settings.ioi_expose_stream_to_ui,
            input_data=request,
        )
        return {"is_ioi": result.is_ioi}

    async def navigate_ioi(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """发送固定 IOI 目标并结束场景。"""

        del state
        await context.events.custom(
            BusinessEventName.NAVIGATION,
            NavigationPayload(target=NavigationTarget.IOI_PURCHASE),
        )
        return {
            "navigation_target": NavigationTarget.IOI_PURCHASE,
            "status": ScenarioStatus.COMPLETED,
        }

    async def recognize_columns(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """调用栏目 Agent 一次并保存全部候选。"""

        fields = self._purchase_fields(state)
        assert fields.product_name is not None
        assert fields.region_code is not None
        assert fields.budget_amount is not None
        request = ColumnRecognitionInput(
            product_name=fields.product_name,
            region_code=fields.region_code,
            budget_amount=fields.budget_amount,
            currency=fields.currency,
        )

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> ColumnRecognitionResult:
            return await self._columns.recognize(request, call_context, stream_sink)

        result = await context.call_delegate(
            name="agent.column_recognition",
            kind=SpanKind.AGENT,
            operation=invoke,
            expose_stream_to_ui=self._settings.column_expose_stream_to_ui,
            input_data=request,
        )
        return {"column_candidates": result.candidates}

    async def handle_no_column(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """无栏目时引导采购热线并结束，不调用商品推荐。"""

        del state
        hotline_text = (
            self._settings.procurement_hotline_text or "未找到相关采购栏目，请联系采购热线。"
        )
        await context.events.text_message(hotline_text)
        return {"status": ScenarioStatus.COMPLETED}

    async def select_single_column(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """只有一个栏目时无需打断用户，直接选中。"""

        del context
        if len(state.column_candidates) != 1:
            raise RuntimeError("单栏目节点收到的候选数量不是 1")
        return {"selected_column": state.column_candidates[0]}

    async def prepare_column_selection(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """多栏目时把当前全部候选写入 Options WaitRequest。"""

        del context
        return {"wait_request": self._waits.column_selection(state.column_candidates)}

    async def wait_for_column_selection(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """从 Checkpoint 候选按 option_id 精确匹配，不再次调用栏目 Agent。"""

        del context
        if state.wait_request is None:
            raise RuntimeError("栏目等待节点没有 WaitRequest")
        resumed = interrupt(state.wait_request.model_dump(mode="json"))
        command = GraphResumeInput.model_validate(resumed)
        if command.operation != BusinessActionOperation.SELECT_OPTION:
            raise InvalidUserInputError("当前步骤只接受栏目选择")
        selected_id = command.values.get("option_id")
        selected = next(
            (
                candidate
                for candidate in state.column_candidates
                if candidate.option_id == selected_id
            ),
            None,
        )
        if selected is None:
            raise InvalidUserInputError("选择的栏目不在当前候选中")
        return {"selected_column": selected, "wait_request": None}

    async def recommend_products(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """调用内部商品推荐 Subgraph；预算不会进入子图。"""

        if state.selected_column is None or state.product_name is None or state.region_code is None:
            raise RuntimeError("商品推荐缺少商品、栏目或区域")
        recommendation = state.recommendation or RecommendationState(
            product_name=state.product_name,
            column_name=state.selected_column.column_name,
            user_id=context.user_id,
            region_code=state.region_code,
            page_size=self._settings.product_page_size,
        )
        async with context.trace.start_span(
            kind=SpanKind.GRAPH,
            name="subgraph.product_recommendation",
            target="product_recommendation",
            input_json=recommendation,
        ) as span:
            result = await self._product_graph.ainvoke(recommendation, context=context)
            span.set_output(result)
        return {"recommendation": RecommendationState.model_validate(result)}

    async def present_recommendation(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """展示当前商品页，或在空结果时直接进入采购方式判断。"""

        recommendation = self._require_recommendation(state)
        if not recommendation.products:
            await context.events.text_message("没有找到符合条件的商品。")
            return {"wait_request": None}

        await context.events.custom(
            BusinessEventName.PRODUCTS,
            ProductsPayload(
                page=recommendation.page,
                page_size=recommendation.page_size,
                has_next=recommendation.has_next,
                products=tuple(
                    ProductView.from_domain(product) for product in recommendation.products
                ),
            ),
        )
        return {
            "wait_request": self._waits.recommendation_actions(has_next=recommendation.has_next)
        }

    async def wait_for_recommendation_action(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """等待换一批、追加商品、其他采购方式或结束。"""

        del context
        if state.wait_request is None:
            raise RuntimeError("推荐操作等待节点没有 WaitRequest")
        resumed = interrupt(state.wait_request.model_dump(mode="json"))
        command = GraphResumeInput.model_validate(resumed)
        allowed = {
            BusinessActionOperation.NEXT_PAGE,
            BusinessActionOperation.APPEND_PRODUCT,
            BusinessActionOperation.OTHER_PROCUREMENT_MODE,
            BusinessActionOperation.END_RECOMMENDATION,
        }
        if command.operation not in allowed:
            raise InvalidUserInputError("当前步骤不接受该操作")
        return {"selected_action": command.operation, "wait_request": None}

    async def advance_product_page(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """“换一批”只增加页码并保留已拆解搜索词。"""

        del context
        recommendation = self._require_recommendation(state)
        if not recommendation.has_next:
            raise InvalidUserInputError("已经没有下一批商品")
        return {
            "recommendation": recommendation.model_copy(
                update={
                    "page": recommendation.page + 1,
                    "products": (),
                    "has_next": False,
                    "result_status": "not_searched",
                    "wait_request": None,
                }
            ),
            "selected_action": None,
        }

    async def reset_for_appended_product(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """清空单商品状态，重新执行完整智能分流。"""

        del context
        # 追加商品相当于重新点击场景入口，但仍属于同一个场景实例。区域来自页面，
        # 可以保留；其余所有单商品状态必须清空，确保重新执行 IOI 和栏目判断。
        return {
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

    async def complete_recommendation(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """用户主动结束本次推荐。"""

        del state, context
        return {"selected_action": None, "status": ScenarioStatus.COMPLETED}

    async def choose_procurement_mode(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """清理推荐操作，下一条条件边按栏目自采标识分支。"""

        del state, context
        return {"selected_action": None}

    async def check_duplicate_self_purchase(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """仅在栏目允许自行采购时调用重复探针。"""

        if state.product_name is None or state.selected_column is None:
            raise RuntimeError("重复自采判断缺少商品或栏目")
        request = DuplicateSelfPurchaseInput(
            product_name=state.product_name,
            column_name=state.selected_column.column_name,
            user_id=context.user_id,
        )

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> DuplicateSelfPurchaseResult:
            return await self._duplicate_self_purchase.check(request, call_context, stream_sink)

        result = await context.call_delegate(
            name="agent.duplicate_self_purchase",
            kind=SpanKind.AGENT,
            operation=invoke,
            expose_stream_to_ui=self._settings.duplicate_self_purchase_expose_stream_to_ui,
            input_data=request,
        )
        return {"duplicate_self_purchase": result.is_duplicate}

    async def prepare_self_purchase(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """未重复自行采购时等待用户点击，而不是立即跳转。"""

        del state, context
        return {
            "wait_request": self._waits.single_navigation_action(
                BusinessActionOperation.GO_SELF_PURCHASE,
                title="该栏目允许自行采购",
                label="自行采购",
            )
        }

    async def wait_for_self_purchase(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """点击自行采购后发送固定导航并结束。"""

        if state.wait_request is None:
            raise RuntimeError("自行采购等待节点没有 WaitRequest")
        resumed = interrupt(state.wait_request.model_dump(mode="json"))
        command = GraphResumeInput.model_validate(resumed)
        if command.operation != BusinessActionOperation.GO_SELF_PURCHASE:
            raise InvalidUserInputError("当前步骤只接受自行采购操作")
        await context.events.custom(
            BusinessEventName.NAVIGATION,
            NavigationPayload(target=NavigationTarget.SELF_PURCHASE),
        )
        return {
            "wait_request": None,
            "navigation_target": NavigationTarget.SELF_PURCHASE,
            "status": ScenarioStatus.COMPLETED,
        }

    async def enter_custom_purchase(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """统一标记进入自定义采购，所有来源都必须经过后续 Queue 节点。"""

        del state, context
        return {"entered_custom_purchase": True, "queue_count": None}

    async def load_custom_queue(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """查询排队数量；失败是唯一明确的非阻塞外围错误。"""

        if not state.entered_custom_purchase:
            raise RuntimeError("未进入自定义采购却调用了排队接口")
        request = QueueInput(user_id=context.user_id)

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> QueueResult:
            del stream_sink
            return await self._queue.get_queue(request, call_context)

        try:
            result = await context.call_delegate(
                name="service.custom_purchase_queue",
                kind=SpanKind.SERVICE,
                operation=invoke,
                input_data=request,
            )
            return {"queue_count": result.count}
        except ProcurementAssistantError:
            # 排队信息只用于提示，不具备资格判断含义。已经进入自定义采购后，不能因
            # 提示接口失败阻止用户办事，因此保留 Trace 错误并继续展示跳转按钮。
            return {"queue_count": None}

    async def prepare_custom_purchase(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """可选展示排队文案，并准备自定义采购按钮。"""

        if state.queue_count is not None and state.queue_count > 0:
            await context.events.custom(
                BusinessEventName.QUEUE,
                QueuePayload.from_count(state.queue_count),
            )
        return {
            "wait_request": self._waits.single_navigation_action(
                BusinessActionOperation.GO_CUSTOM_PURCHASE,
                title="你可以进入自定义采购",
                label="自定义采购",
            )
        }

    async def wait_for_custom_purchase(
        self, state: SmartRoutingState, context: ExecutionContext
    ) -> dict[str, Any]:
        """用户点击自定义采购时才导航并结束排队等待场景。"""

        if state.wait_request is None:
            raise RuntimeError("自定义采购等待节点没有 WaitRequest")
        resumed = interrupt(state.wait_request.model_dump(mode="json"))
        command = GraphResumeInput.model_validate(resumed)
        if command.operation != BusinessActionOperation.GO_CUSTOM_PURCHASE:
            raise InvalidUserInputError("当前步骤只接受自定义采购操作")
        await context.events.custom(
            BusinessEventName.NAVIGATION,
            NavigationPayload(target=NavigationTarget.CUSTOM_PURCHASE),
        )
        return {
            "wait_request": None,
            "navigation_target": NavigationTarget.CUSTOM_PURCHASE,
            "status": ScenarioStatus.COMPLETED,
        }

    @staticmethod
    def _purchase_fields(state: SmartRoutingState) -> PurchaseFields:
        """把 State 中分散字段集中成 Delegate 输入并再次验证。"""

        return PurchaseFields(
            product_name=state.product_name,
            purchase_purpose=state.purchase_purpose,
            budget_amount=state.budget_amount,
            currency=state.currency,
            region_code=state.region_code,
        )

    @staticmethod
    def _require_recommendation(state: SmartRoutingState) -> RecommendationState:
        """取得已存在的推荐 State，否则报告开发错误。"""

        if state.recommendation is None:
            raise RuntimeError("当前节点缺少商品推荐 State")
        return state.recommendation
