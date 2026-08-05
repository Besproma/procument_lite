"""智能分流等业务场景独有的 AG-UI CUSTOM payload。"""

from enum import StrEnum
from typing import Any

from pydantic import Field

from procurement_assistant.business.domain.procurement import NavigationTarget, Product
from procurement_assistant.core.protocol.base import ProtocolModel


class BusinessEventName(StrEnum):
    """采购业务节点会发送、但 Core 不需要理解的事件名。"""

    PRODUCTS = "procurement.products"
    QUEUE = "procurement.queue"
    NAVIGATION = "procurement.navigation"


class ProductView(ProtocolModel):
    """前端商品卡所需字段。"""

    product_id: str
    name: str
    price: float | None = None
    currency: str | None = None
    image_url: str | None = None
    delivery_text: str | None = None
    badges: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, product: Product) -> "ProductView":
        """集中完成 Decimal 到 JSON number 的展示映射。"""

        return cls(
            product_id=product.product_id,
            name=product.name,
            price=float(product.price) if product.price is not None else None,
            currency=product.currency,
            image_url=product.image_url,
            delivery_text=product.delivery_text,
            badges=product.badges,
            metadata=product.metadata,
        )


class ProductsPayload(ProtocolModel):
    """搜索服务已经排序后的当前商品页。"""

    title: str = "为你推荐"
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    has_next: bool
    products: tuple[ProductView, ...]


class QueuePayload(ProtocolModel):
    """只在排队数量大于零时发送。"""

    count: int = Field(gt=0)
    text: str

    @classmethod
    def from_count(cls, count: int) -> "QueuePayload":
        """使用固定模板生成排队文案，禁止交给模型改写。"""

        return cls(
            count=count,
            text=f"前面还有{count}单在采购受理中哦～，审批完成后，采购将按顺序为您处理！",
        )


class NavigationPayload(ProtocolModel):
    """固定页面目标；后端永远不发送任意 URL。"""

    target: NavigationTarget
    params: dict[str, str] = Field(default_factory=dict)
