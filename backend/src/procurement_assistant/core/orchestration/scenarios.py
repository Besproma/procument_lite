"""Core 可执行场景的通用定义和只读注册表。"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from procurement_assistant.core.delegates.model.interface import ScenarioToolDescription
from procurement_assistant.core.domain.errors import ConfigurationError, InvalidUserInputError
from procurement_assistant.core.orchestration.tool_contract import ScenarioTool


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """Business 注入 Core 的一个完整场景。

    一个定义把“给 ReAct 看的说明”“创建初始状态的 Tool”和“真正执行的 LangGraph”
    放在一起，避免旧实现中 Catalog 和 graphs 两份字典可能漏配或写错同一个 ID。
    """

    scenario_id: str
    display_name: str
    description: str
    tool: ScenarioTool
    graph: Any

    def model_description(self) -> ScenarioToolDescription:
        """只向模型暴露安全的文字描述，不暴露 Python 对象。"""

        return ScenarioToolDescription(
            tool_id=self.scenario_id,
            display_name=self.display_name,
            description=self.description,
        )


class ScenarioRegistry:
    """启动时构造、运行时只读的场景目录。"""

    def __init__(self, definitions: Sequence[ScenarioDefinition]) -> None:
        items: dict[str, ScenarioDefinition] = {}
        for definition in definitions:
            scenario_id = definition.scenario_id
            if not scenario_id.strip():
                raise ConfigurationError("场景 scenario_id 不能为空")
            if not definition.display_name.strip():
                raise ConfigurationError(f"场景 {scenario_id} 的 display_name 不能为空")
            if not definition.description.strip():
                raise ConfigurationError(f"场景 {scenario_id} 的 description 不能为空")
            if scenario_id in items:
                raise ConfigurationError(f"场景重复注册：{scenario_id}")
            if definition.tool.tool_id != scenario_id:
                raise ConfigurationError(
                    f"场景 {scenario_id} 与 Tool ID {definition.tool.tool_id} 不一致"
                )
            if not callable(getattr(definition.tool, "create_initial_state", None)):
                raise ConfigurationError(f"场景 {scenario_id} 的 Tool 缺少初始 State 创建方法")
            if not callable(getattr(definition.graph, "ainvoke", None)):
                raise ConfigurationError(f"场景 {scenario_id} 没有可执行 LangGraph")
            items[scenario_id] = definition
        if not items:
            raise ConfigurationError("至少需要注册一个场景")
        self._items = MappingProxyType(items)

    def require(self, scenario_id: str) -> ScenarioDefinition:
        """取得已注册场景；外部传入未知 ID 时返回安全的用户输入错误。"""

        try:
            return self._items[scenario_id]
        except KeyError as exc:
            raise InvalidUserInputError("不支持的场景") from exc

    def contains(self, scenario_id: str) -> bool:
        """判断模型结果是否仍在 Business 注入的白名单内。"""

        return scenario_id in self._items

    def __iter__(self) -> Iterator[ScenarioDefinition]:
        """按 Business 显式登记顺序遍历全部场景。"""

        return iter(self._items.values())
