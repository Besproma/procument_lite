"""知识推荐场景的依赖、说明、入口 Tool 和 Graph 装配。"""

from dataclasses import dataclass
from typing import Any

from procurement_assistant.business.delegates.services.cached_knowledge import (
    CachedKnowledgeDelegate,
)
from procurement_assistant.business.interaction.wait_factory import BusinessWaitRequestFactory
from procurement_assistant.business.scenarios.knowledge.graph import build_knowledge_graph
from procurement_assistant.business.scenarios.knowledge.nodes import KnowledgeNodes
from procurement_assistant.business.tools.start_knowledge_recommendation import (
    StartKnowledgeRecommendationTool,
)
from procurement_assistant.core.orchestration.scenarios import ScenarioDefinition


@dataclass(frozen=True, slots=True)
class KnowledgeScenarioDependencies:
    """创建知识推荐 Graph 必须明确提供的全部依赖。"""

    knowledge: CachedKnowledgeDelegate
    waits: BusinessWaitRequestFactory
    checkpointer: Any


def build_knowledge_definition(
    dependencies: KnowledgeScenarioDependencies,
) -> ScenarioDefinition:
    """构建知识推荐的完整场景定义。"""

    nodes = KnowledgeNodes(
        knowledge=dependencies.knowledge,
        waits=dependencies.waits,
    )
    return ScenarioDefinition(
        scenario_id="knowledge_recommendation",
        display_name="知识推荐",
        description="当用户希望查询采购知识、规则或说明时使用。",
        tool=StartKnowledgeRecommendationTool(),
        graph=build_knowledge_graph(nodes, checkpointer=dependencies.checkpointer),
    )
