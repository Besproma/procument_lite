"""Action 输入校验的通用静态注册表。"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from procurement_assistant.core.domain.errors import ConfigurationError, InvalidUserInputError

ValidatedValues = dict[str, Any]
PostValidator = Callable[[ValidatedValues, Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class ActionInputDefinition:
    """一个 Action 输入模型及其可选业务补充校验。"""

    schema_id: str
    input_model: type[BaseModel]
    post_validator: PostValidator | None = None


class ActionInputRegistry:
    """Core 用于校验表单和按钮输入的只读目录。

    Business 在启动时明确传入定义。数据库只保存 ``schema_id``，Core 不会根据字符串
    import Python 类，也不会扫描目录寻找实现。
    """

    def __init__(self, definitions: Sequence[ActionInputDefinition]) -> None:
        items: dict[str, ActionInputDefinition] = {}
        for definition in definitions:
            if not definition.schema_id:
                raise ConfigurationError("Action 输入 schema_id 不能为空")
            if definition.schema_id in items:
                raise ConfigurationError(f"Action 输入 schema_id 重复注册：{definition.schema_id}")
            items[definition.schema_id] = definition
        if not items:
            raise ConfigurationError("至少需要注册一个 Action 输入模型")
        self._items = MappingProxyType(items)

    def validate(
        self,
        schema_id: str,
        values: Mapping[str, Any],
        *,
        action_payload: Mapping[str, Any] | None = None,
    ) -> ValidatedValues:
        """找到静态模型，校验用户值并返回统一的 snake_case 字典。"""

        definition = self._items.get(schema_id)
        if definition is None:
            raise ConfigurationError("服务端 Action 输入 Schema 不存在")
        try:
            validated = definition.input_model.model_validate(dict(values))
        except ValueError as exc:
            # 不直接回显 Pydantic 的详细错误，其中可能包含用户提交的原始内容。
            raise InvalidUserInputError("提交内容不符合当前操作要求") from exc
        normalized = validated.model_dump(exclude_none=True)
        if definition.post_validator is not None:
            definition.post_validator(normalized, action_payload or {})
        return normalized

    def contains(self, schema_id: str) -> bool:
        """供启动校验确认等待点引用了已注册的输入模型。"""

        return schema_id in self._items
