"""采购业务 Action/Form 的输入模型和补充校验。"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from procurement_assistant.core.domain.errors import ConfigurationError, InvalidUserInputError


class ActionInputModel(BaseModel):
    """拒绝额外字段的一次性操作输入基类。"""

    model_config = ConfigDict(extra="forbid")


class PurchaseFieldsFormInput(ActionInputModel):
    """补充智能分流必填信息。

    字段允许为空是因为同一个模型服务多个动态缺失组合；Graph 合并后会再次检查所有必填
    字段是否齐全，不能因前端只提交部分值而越过业务校验。
    """

    product_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        validation_alias=AliasChoices("productName", "product_name"),
    )
    purchase_purpose: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        validation_alias=AliasChoices("purchasePurpose", "purchase_purpose"),
    )
    budget_amount: Decimal | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("budgetAmount", "budget_amount"),
    )
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    region_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("regionCode", "region_code"),
    )


class KnowledgeQueryInput(ActionInputModel):
    """知识查询 key；不 strip、不改大小写、不改标点。"""

    query_text: str = Field(
        min_length=1,
        max_length=1000,
        validation_alias=AliasChoices("queryText", "query_text"),
    )


class ColumnSelectionInput(ActionInputModel):
    """用户从已保存栏目候选中选择的 option_id。"""

    option_id: str = Field(
        min_length=1,
        max_length=500,
        validation_alias=AliasChoices("optionId", "option_id"),
    )


class EmptyActionInput(ActionInputModel):
    """不需要业务参数的按钮；额外 data 会被拒绝。"""


def validate_column_selection(
    values: dict[str, Any],
    action_payload: Mapping[str, Any],
) -> None:
    """确认栏目编号确实来自上一次保存的候选集合。

    这一步必须在一次性 Action 被消费前执行。否则用户提交任意编号后，等 Graph 才发现
    错误时，原按钮已经失效，用户无法重新选择。
    """

    raw_allowed = action_payload.get("option_ids")
    if not isinstance(raw_allowed, list) or not all(
        isinstance(option_id, str) for option_id in raw_allowed
    ):
        raise ConfigurationError("栏目 Action 缺少有效候选集合")
    if values["option_id"] not in raw_allowed:
        raise InvalidUserInputError("选择的栏目不在当前候选中")
