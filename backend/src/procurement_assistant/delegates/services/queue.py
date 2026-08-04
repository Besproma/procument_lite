"""自定义采购排队信息 Delegate。"""

from typing import Protocol

from procurement_assistant.delegates.common.call_context import DelegateCallContext
from procurement_assistant.domain.errors import ConfigurationError
from procurement_assistant.domain.procurement import QueueInput, QueueResult


class QueueDelegate(Protocol):
    """只要进入自定义采购就查询排队数量。"""

    async def get_queue(self, request: QueueInput, context: DelegateCallContext) -> QueueResult:
        """返回数量；调用失败由 Graph 按非阻塞规则处理。"""


class NotConfiguredQueueDelegate:
    """正式排队协议尚未提供时使用的明确阻塞实现。"""

    async def get_queue(
        self,
        request: QueueInput,
        context: DelegateCallContext,
    ) -> QueueResult:
        del request, context
        raise ConfigurationError("自定义采购排队接口尚未完成生产映射")
