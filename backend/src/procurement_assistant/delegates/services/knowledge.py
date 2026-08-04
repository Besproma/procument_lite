"""知识全集 Delegate。"""

from typing import Protocol

from procurement_assistant.delegates.common.call_context import DelegateCallContext
from procurement_assistant.domain.errors import ConfigurationError
from procurement_assistant.domain.procurement import KnowledgeResult


class KnowledgeDelegate(Protocol):
    """获取全部知识 key/value，精确匹配由主服务代码完成。"""

    async def fetch_all(self, context: DelegateCallContext) -> KnowledgeResult:
        """返回已经校验且 key 唯一的完整知识集合。"""


class NotConfiguredKnowledgeDelegate:
    """正式知识全集协议尚未提供时使用的明确阻塞实现。"""

    async def fetch_all(self, context: DelegateCallContext) -> KnowledgeResult:
        del context
        raise ConfigurationError("知识接口尚未完成生产映射")
