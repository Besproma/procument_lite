"""采购领域的稳定输入输出模型。

这些模型描述主服务内部真正关心的业务含义。外围 Agent 的字段名可以不同，但必须在
各自 Delegate 中映射成这里的模型后，才允许进入 LangGraph State。
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
CurrencyCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=8)]
RegionCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class StrictModel(BaseModel):
    """拒绝未声明字段的领域模型基类。

    禁止额外字段可以及时暴露外围协议变化，避免一个拼错的字段被静默忽略后导致错误
    业务分支。所有领域模型默认不可变，节点通过创建新值更新 State。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class PurchaseFields(StrictModel):
    """智能分流所需的单件商品信息。"""

    product_name: NonBlankText | None = None
    purchase_purpose: NonBlankText | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency: CurrencyCode | None = None
    region_code: RegionCode | None = None

    @property
    def missing_required_fields(self) -> tuple[str, ...]:
        """按固定顺序返回必须继续追问的字段名。"""

        missing: list[str] = []
        if self.product_name is None:
            missing.append("productName")
        if self.purchase_purpose is None:
            missing.append("purchasePurpose")
        if self.budget_amount is None:
            missing.append("budgetAmount")
        if self.region_code is None:
            missing.append("regionCode")
        return tuple(missing)


class PurchaseFieldExtractionResult(StrictModel):
    """模型从用户原文中可靠提取出的字段；缺失值必须保持为空。"""

    product_name: NonBlankText | None = None
    purchase_purpose: NonBlankText | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency: CurrencyCode | None = None


class PurchaseFieldExtractionInput(StrictModel):
    """采购字段提取模型任务的原始输入。"""

    original_user_text: str = Field(min_length=1, max_length=100_000)


class IOIProcurementInput(StrictModel):
    """IOI 判断 Delegate 的稳定输入。"""

    fields: PurchaseFields


class IOIProcurementResult(StrictModel):
    """IOI 判断的结构化结论。"""

    is_ioi: bool


class ColumnRecognitionInput(StrictModel):
    """栏目识别的稳定输入，币种按确认规则允许为空。"""

    product_name: NonBlankText
    region_code: RegionCode
    budget_amount: Decimal = Field(ge=0)
    currency: CurrencyCode | None = None


class ColumnCandidate(StrictModel):
    """栏目识别返回的一个可选栏目。"""

    option_id: NonBlankText
    column_name: NonBlankText
    category_name: NonBlankText
    self_purchase_allowed: bool


class ColumnRecognitionResult(StrictModel):
    """一次栏目识别调用返回的全部候选。"""

    candidates: tuple[ColumnCandidate, ...] = ()

    @field_validator("candidates")
    @classmethod
    def option_ids_must_be_unique(
        cls, candidates: tuple[ColumnCandidate, ...]
    ) -> tuple[ColumnCandidate, ...]:
        """阻止重复 option_id 让用户选择落到不确定结果。"""

        option_ids = [candidate.option_id for candidate in candidates]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("栏目候选 option_id 必须唯一")
        return candidates


class SearchTermsResult(StrictModel):
    """模型拆解出的有效商品搜索词。"""

    search_terms: tuple[NonBlankText, ...] = Field(min_length=1, max_length=20)


class ProductSearchTermsInput(StrictModel):
    """商品搜索词模型任务的唯一输入，明确不包含预算。"""

    product_name: NonBlankText
    column_name: NonBlankText


class ProductSearchInput(StrictModel):
    """商品搜索服务的稳定分页输入；明确不包含预算。"""

    search_terms: tuple[NonBlankText, ...] = Field(min_length=1)
    column_name: NonBlankText
    user_id: NonBlankText
    region_code: RegionCode
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=20)


class Product(StrictModel):
    """可安全展示并交给前端加购的商品。"""

    product_id: NonBlankText
    name: NonBlankText
    price: Decimal | None = Field(default=None, ge=0)
    currency: CurrencyCode | None = None
    image_url: str | None = None
    delivery_text: str | None = Field(default=None, max_length=200)
    badges: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductSearchResult(StrictModel):
    """搜索接口已经完成排序后的当前页结果。"""

    products: tuple[Product, ...] = ()
    has_next: bool = False


class DuplicateSelfPurchaseInput(StrictModel):
    """重复自行采购探针的稳定输入。"""

    product_name: NonBlankText
    column_name: NonBlankText
    user_id: NonBlankText


class DuplicateSelfPurchaseResult(StrictModel):
    """业务是否禁止本次重复自行采购。"""

    is_duplicate: bool


class QueueInput(StrictModel):
    """进入自定义采购时查询排队数量的稳定输入。"""

    user_id: NonBlankText


class QueueResult(StrictModel):
    """排队数量；外部没有数量时保持为空。"""

    count: int | None = Field(default=None, ge=0)


class KnowledgeEntry(StrictModel):
    """外部知识接口的一条原始 key/value。"""

    key: str = Field(min_length=1, max_length=1000)
    value: str = Field(max_length=100_000)


class KnowledgeResult(StrictModel):
    """外部接口返回的全部知识。"""

    entries: tuple[KnowledgeEntry, ...] = ()

    @field_validator("entries")
    @classmethod
    def keys_must_be_unique(cls, entries: tuple[KnowledgeEntry, ...]) -> tuple[KnowledgeEntry, ...]:
        """精确匹配要求 key 唯一，重复时不能任意挑选 value。"""

        keys = [entry.key for entry in entries]
        if len(keys) != len(set(keys)):
            raise ValueError("知识 key 必须唯一")
        return entries


class NavigationTarget(StrEnum):
    """后端唯一允许发送的三个固定跳转目标。"""

    IOI_PURCHASE = "ioi_purchase"
    SELF_PURCHASE = "self_purchase"
    CUSTOM_PURCHASE = "custom_purchase"


class MemoryPatch(StrictModel):
    """记忆模型生成的结构化增量，而不是整份 JSON 覆盖。"""

    updates: dict[str, Any] = Field(default_factory=dict)
    remove_keys: tuple[str, ...] = ()


class MemoryUpdateInput(StrictModel):
    """交给记忆模型的完整、明确输入。

    ``turn_input`` 使用本次已校验的 Run 输入，而不是让模型重新读取整段会话历史；
    ``assistant_texts`` 只包含已经允许展示给用户的文字。当前完整记忆作为参考传入，但
    模型只能返回 ``MemoryPatch``，不能用一次生成结果覆盖整份 JSON。
    """

    turn_input: dict[str, Any]
    assistant_texts: tuple[str, ...] = ()
    current_memory: dict[str, Any] = Field(default_factory=dict)


RecommendationResultStatus = Literal["not_searched", "has_products", "empty"]
