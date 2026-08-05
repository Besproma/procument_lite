"""智能分流场景的依赖、说明、入口 Tool 和 Graph 装配。"""

from dataclasses import dataclass
from typing import Any

from procurement_assistant.business.config.settings import BusinessSettings
from procurement_assistant.business.delegates.agents.column_recognition import (
    ColumnRecognitionDelegate,
)
from procurement_assistant.business.delegates.agents.duplicate_self_purchase import (
    DuplicateSelfPurchaseDelegate,
)
from procurement_assistant.business.delegates.agents.ioi import IOIProcurementDelegate
from procurement_assistant.business.delegates.services.queue import QueueDelegate
from procurement_assistant.business.interaction.wait_factory import BusinessWaitRequestFactory
from procurement_assistant.business.scenarios.smart_routing.graph import build_smart_routing_graph
from procurement_assistant.business.scenarios.smart_routing.nodes import SmartRoutingNodes
from procurement_assistant.business.tools.start_smart_routing import StartSmartRoutingTool
from procurement_assistant.core.delegates.model.interface import ModelDelegate
from procurement_assistant.core.orchestration.scenarios import ScenarioDefinition


@dataclass(frozen=True, slots=True)
class SmartRoutingDependencies:
    """创建智能分流 Graph 必须明确提供的全部依赖。"""

    settings: BusinessSettings
    model: ModelDelegate
    ioi: IOIProcurementDelegate
    columns: ColumnRecognitionDelegate
    duplicate_self_purchase: DuplicateSelfPurchaseDelegate
    queue: QueueDelegate
    product_graph: Any
    waits: BusinessWaitRequestFactory
    checkpointer: Any


def build_smart_routing_definition(
    dependencies: SmartRoutingDependencies,
) -> ScenarioDefinition:
    """构建一个完整定义，避免 ID、Tool 和 Graph 分散在多份映射中。"""

    nodes = SmartRoutingNodes(
        settings=dependencies.settings,
        model=dependencies.model,
        ioi=dependencies.ioi,
        columns=dependencies.columns,
        duplicate_self_purchase=dependencies.duplicate_self_purchase,
        queue=dependencies.queue,
        product_graph=dependencies.product_graph,
        waits=dependencies.waits,
    )
    return ScenarioDefinition(
        scenario_id="smart_routing",
        display_name="智能分流",
        description="当用户希望购买商品，并需要推荐商品或采购方式时使用。",
        tool=StartSmartRoutingTool(),
        graph=build_smart_routing_graph(nodes, checkpointer=dependencies.checkpointer),
    )
