"""栏目识别 Delegate。"""

from typing import Protocol

from procurement_assistant.business.domain.procurement import (
    ColumnRecognitionInput,
    ColumnRecognitionResult,
)
from procurement_assistant.core.delegates.common.call_context import DelegateCallContext
from procurement_assistant.core.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.core.domain.errors import ConfigurationError


class ColumnRecognitionDelegate(Protocol):
    """一次返回全部栏目候选。"""

    async def recognize(
        self,
        request: ColumnRecognitionInput,
        context: DelegateCallContext,
        stream_sink: AgentStreamSink | None = None,
    ) -> ColumnRecognitionResult:
        """返回候选；多栏目选择恢复时禁止再次调用本方法。"""


class NotConfiguredColumnRecognitionDelegate:
    """正式栏目协议尚未提供时使用的明确阻塞实现。"""

    async def recognize(
        self,
        request: ColumnRecognitionInput,
        context: DelegateCallContext,
        stream_sink: AgentStreamSink | None = None,
    ) -> ColumnRecognitionResult:
        del request, context, stream_sink
        raise ConfigurationError("栏目识别接口尚未完成生产映射")
