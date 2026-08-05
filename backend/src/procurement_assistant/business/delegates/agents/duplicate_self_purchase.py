"""重复自行采购探针 Delegate。"""

from typing import Protocol

from procurement_assistant.business.domain.procurement import (
    DuplicateSelfPurchaseInput,
    DuplicateSelfPurchaseResult,
)
from procurement_assistant.core.delegates.common.call_context import DelegateCallContext
from procurement_assistant.core.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.core.domain.errors import ConfigurationError


class DuplicateSelfPurchaseDelegate(Protocol):
    """判断本次自行采购是否与历史自行采购重复。"""

    async def check(
        self,
        request: DuplicateSelfPurchaseInput,
        context: DelegateCallContext,
        stream_sink: AgentStreamSink | None = None,
    ) -> DuplicateSelfPurchaseResult:
        """返回业务是否禁止重复自行采购。"""


class NotConfiguredDuplicateSelfPurchaseDelegate:
    """正式重复自采协议尚未提供时使用的明确阻塞实现。"""

    async def check(
        self,
        request: DuplicateSelfPurchaseInput,
        context: DelegateCallContext,
        stream_sink: AgentStreamSink | None = None,
    ) -> DuplicateSelfPurchaseResult:
        del request, context, stream_sink
        raise ConfigurationError("重复自行采购判断接口尚未完成生产映射")
