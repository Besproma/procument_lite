"""采购业务场景的总注册入口。"""

from procurement_assistant.core.orchestration.scenarios import (
    ScenarioDefinition,
    ScenarioRegistry,
)


def build_scenario_registry(
    *,
    smart_routing: ScenarioDefinition,
    knowledge_recommendation: ScenarioDefinition,
) -> ScenarioRegistry:
    """显式登记全部场景。

    新增场景时需要新增自己的 ``definition.py``，然后在本函数参数和元组中各增加一项。
    场景名称和模型描述随完整定义放在对应的 ``definition.py``，这里负责把所有定义集中
    汇总并交给 Core 做启动校验。这是有意保留的一处清晰修改点，不使用目录扫描或动态
    import。
    """

    return ScenarioRegistry((smart_routing, knowledge_recommendation))
