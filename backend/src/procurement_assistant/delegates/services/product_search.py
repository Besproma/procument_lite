"""商品搜索 Delegate。"""

from typing import Protocol

from procurement_assistant.delegates.common.call_context import DelegateCallContext
from procurement_assistant.domain.errors import ConfigurationError
from procurement_assistant.domain.procurement import ProductSearchInput, ProductSearchResult


class ProductSearchDelegate(Protocol):
    """调用已经完成加权排序的分页搜索接口。"""

    async def search(
        self, request: ProductSearchInput, context: DelegateCallContext
    ) -> ProductSearchResult:
        """原样返回搜索顺序，主服务和模型不得二次重排。"""


class NotConfiguredProductSearchDelegate:
    """正式搜索协议尚未提供时使用的明确阻塞实现。"""

    async def search(
        self,
        request: ProductSearchInput,
        context: DelegateCallContext,
    ) -> ProductSearchResult:
        del request, context
        raise ConfigurationError("商品搜索接口尚未完成生产映射")
