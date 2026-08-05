"""知识推荐 Scenario Graph 节点。"""

from typing import Any

from langgraph.types import interrupt

from procurement_assistant.business.delegates.services.cached_knowledge import (
    CachedKnowledgeDelegate,
    KnowledgeCacheRead,
)
from procurement_assistant.business.interaction.operations import BusinessActionOperation
from procurement_assistant.business.interaction.wait_factory import BusinessWaitRequestFactory
from procurement_assistant.business.scenarios.knowledge.state import KnowledgeState
from procurement_assistant.core.delegates.common.call_context import DelegateCallContext
from procurement_assistant.core.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.core.domain.errors import InvalidUserInputError
from procurement_assistant.core.domain.lifecycle import ScenarioStatus
from procurement_assistant.core.observability.models import SpanKind
from procurement_assistant.core.orchestration.resume import GraphResumeInput
from procurement_assistant.core.orchestration.runtime import ExecutionContext


class KnowledgeNodes:
    """知识推荐节点集合。

    本类没有 ModelDelegate 依赖，这是架构上的强约束：精确匹配和 value 原样返回不能被
    模型语义搜索、总结或润色悄悄替代。
    """

    def __init__(
        self,
        *,
        knowledge: CachedKnowledgeDelegate,
        waits: BusinessWaitRequestFactory,
    ) -> None:
        self._knowledge = knowledge
        self._waits = waits

    async def prepare_query(
        self, state: KnowledgeState, context: ExecutionContext
    ) -> dict[str, Any]:
        """按钮进入且没有 key 时准备查询表单。"""

        del context
        if state.query_text is not None:
            return {"wait_request": None}
        return {"wait_request": self._waits.knowledge_query()}

    async def wait_for_query(
        self, state: KnowledgeState, context: ExecutionContext
    ) -> dict[str, Any]:
        """等待用户填写原始 key，不 trim、不改大小写或标点。"""

        del context
        if state.wait_request is None:
            raise RuntimeError("知识查询等待节点没有 WaitRequest")
        resumed = interrupt(state.wait_request.model_dump(mode="json"))
        command = GraphResumeInput.model_validate(resumed)
        if command.operation != BusinessActionOperation.SUBMIT_FORM:
            raise InvalidUserInputError("当前步骤只接受知识查询表单")
        query_text = command.values.get("query_text")
        if not isinstance(query_text, str) or query_text == "":
            raise InvalidUserInputError("知识查询内容不能为空")
        return {"query_text": query_text, "wait_request": None}

    async def exact_match(self, state: KnowledgeState, context: ExecutionContext) -> dict[str, Any]:
        """加载知识全集并用 Python 字符串完全相等比较。"""

        if state.query_text is None:
            raise RuntimeError("精确匹配节点缺少 query_text")

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> KnowledgeCacheRead:
            del stream_sink
            return await self._knowledge.get(call_context)

        loaded = await context.call_delegate(
            name="service.knowledge",
            kind=SpanKind.SERVICE,
            operation=invoke,
            input_data={"query_key": state.query_text},
        )
        entries_by_key = {entry.key: entry.value for entry in loaded.result.entries}
        if state.query_text in entries_by_key:
            return {
                "match_found": True,
                "matched_value": entries_by_key[state.query_text],
                "cache_source": loaded.source,
            }
        return {
            "match_found": False,
            "matched_value": None,
            "cache_source": loaded.source,
        }

    async def respond(self, state: KnowledgeState, context: ExecutionContext) -> dict[str, Any]:
        """命中时逐字返回 value，未命中使用固定文案。"""

        if state.match_found is True:
            # value 直接进入标准文字事件，绝不调用模型，也不添加前后缀，确保外部知识
            # 内容逐字保持不变。
            assert state.matched_value is not None
            await context.events.text_message(state.matched_value)
        else:
            await context.events.text_message("未找到相关知识")
        return {"status": ScenarioStatus.COMPLETED}
