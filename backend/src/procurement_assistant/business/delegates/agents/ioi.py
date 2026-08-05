"""IOI 采购判断 Delegate。"""

from typing import Protocol

from procurement_assistant.business.domain.procurement import (
    IOIProcurementInput,
    IOIProcurementResult,
)
from procurement_assistant.core.delegates.common.call_context import DelegateCallContext
from procurement_assistant.core.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.core.domain.errors import ConfigurationError


class IOIProcurementDelegate(Protocol):
    """判断一次采购是否应进入 IOI 页面。"""

    async def judge(
        self,
        request: IOIProcurementInput,
        context: DelegateCallContext,
        stream_sink: AgentStreamSink | None = None,
    ) -> IOIProcurementResult:
        """返回校验后的最终判断；流事件绝不能代替最终结果。"""


class NotConfiguredIOIProcurementDelegate:
    """正式 IOI 协议尚未提供时使用的明确阻塞实现。"""

    async def judge(
        self,
        request: IOIProcurementInput,
        context: DelegateCallContext,
        stream_sink: AgentStreamSink | None = None,
    ) -> IOIProcurementResult:
        del request, context, stream_sink
        raise ConfigurationError("IOI 采购判断接口尚未完成生产映射")
