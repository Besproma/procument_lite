"""所有 Tool 名称、描述和实现对象的唯一静态目录。"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from procurement_assistant.delegates.model.interface import ScenarioToolDescription
from procurement_assistant.orchestration.tools.interface import ScenarioTool
from procurement_assistant.orchestration.tools.start_knowledge_recommendation import (
    StartKnowledgeRecommendationTool,
)
from procurement_assistant.orchestration.tools.start_smart_routing import StartSmartRoutingTool


@dataclass(frozen=True, slots=True)
class ScenarioCatalogItem:
    """集中展示给开发者和 ReAct 的一个 Scenario Tool。"""

    tool_id: str
    display_name: str
    description: str
    tool: ScenarioTool

    def model_description(self) -> ScenarioToolDescription:
        """转换成模型可见字段，不暴露 Python 对象。"""

        return ScenarioToolDescription(
            tool_id=self.tool_id,
            display_name=self.display_name,
            description=self.description,
        )


def build_scenario_catalog() -> Mapping[str, ScenarioCatalogItem]:
    """显式创建只读 Scenario Catalog。

    新增场景的学习成本固定为：新增一个 Tool 文件、在这里 import 并增加一项、在
    Composition Root 装配 Graph。没有反射扫描、Manifest 或数据库动态注册。
    """

    smart_routing = StartSmartRoutingTool()
    knowledge = StartKnowledgeRecommendationTool()
    items = {
        smart_routing.tool_id: ScenarioCatalogItem(
            tool_id=smart_routing.tool_id,
            display_name="智能分流",
            description="当用户希望购买商品，并需要推荐商品或采购方式时使用。",
            tool=smart_routing,
        ),
        knowledge.tool_id: ScenarioCatalogItem(
            tool_id=knowledge.tool_id,
            display_name="知识推荐",
            description="当用户希望查询采购知识、规则或说明时使用。",
            tool=knowledge,
        ),
    }
    return MappingProxyType(items)


# 当前确认场景没有需要跨 Graph 复用或暴露给内部 ReAct 的 Atomic Tool。保留空目录而
# 不创建无用途空壳类；未来新增时仍必须显式代码装配。
ATOMIC_TOOL_CATALOG: Mapping[str, object] = MappingProxyType({})
