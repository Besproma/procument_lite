"""所有 Action/Form 恢复输入的静态 Pydantic 模型。"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from procurement_assistant.domain.errors import ConfigurationError, InvalidUserInputError
from procurement_assistant.orchestration.actions import ActionOperation


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


ACTION_INPUT_MODELS: dict[str, type[ActionInputModel]] = {
    "purchase_fields_form": PurchaseFieldsFormInput,
    "knowledge_query_form": KnowledgeQueryInput,
    "column_selection": ColumnSelectionInput,
    "empty_action": EmptyActionInput,
}


class GraphResumeInput(BaseModel):
    """Graph Runner 校验 Action 后传给 ``interrupt()`` 的可信恢复值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: ActionOperation
    values: dict[str, Any] = Field(default_factory=dict)


def validate_action_values(
    schema_id: str,
    values: dict[str, Any],
    *,
    action_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """用静态映射校验用户提交值并返回 snake_case 字典。

    数据库只保存 ``schema_id``，不保存 Python import 路径。未知 ID 直接视为服务器配置
    错误，绝不能根据数据库字符串动态导入任意类。
    """

    model_type = ACTION_INPUT_MODELS.get(schema_id)
    if model_type is None:
        # Schema ID 来自服务端 Checkpoint；未知值表示部署代码和持久化数据不一致，
        # 不是用户输入错误，也不能根据它动态 import 任意模型。
        raise ConfigurationError("服务端 Action 输入 Schema 不存在")
    try:
        validated = model_type.model_validate(values)
    except ValueError as exc:
        # Pydantic 的字段错误不能直接泄露给前端（其中可能包含原始输入），但需要让
        # API 返回 400，并且在入口消费 Action 之前终止，保证用户还能重新提交。
        raise InvalidUserInputError("提交内容不符合当前操作要求") from exc
    normalized = validated.model_dump(exclude_none=True)
    if schema_id == "column_selection":
        # 栏目候选已经在上一次 Agent 调用后写入 Action payload。只检查“非空字符串”
        # 会让用户构造任意 optionId，恢复节点才发现时 Action 已经被消费；因此入口和
        # Graph 都必须做这次精确集合匹配。旧 Checkpoint 没有该字段时按服务端配置错误
        # 处理，而不是放宽为任意值。
        raw_allowed = (action_payload or {}).get("option_ids")
        if not isinstance(raw_allowed, list) or not all(
            isinstance(option_id, str) for option_id in raw_allowed
        ):
            raise ConfigurationError("栏目 Action 缺少有效候选集合")
        if normalized["option_id"] not in raw_allowed:
            raise InvalidUserInputError("选择的栏目不在当前候选中")
    return normalized
