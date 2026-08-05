"""商品推荐 Subgraph State。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from procurement_assistant.business.domain.procurement import Product
from procurement_assistant.core.orchestration.actions import WaitRequest


class RecommendationState(BaseModel):
    """一个商品在推荐阶段的搜索与分页状态。

    该 State 明确没有预算字段。换一批只修改 ``page`` 并复用 ``search_terms``，从数据
    结构上阻止模型被重复调用或预算意外参与推荐。
    """

    model_config = ConfigDict(extra="forbid")

    product_name: str
    column_name: str
    user_id: str
    region_code: str
    search_terms: tuple[str, ...] = ()
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=3, ge=1, le=20)
    products: tuple[Product, ...] = ()
    has_next: bool = False
    result_status: Literal["not_searched", "has_products", "empty"] = "not_searched"
    wait_request: WaitRequest | None = None
