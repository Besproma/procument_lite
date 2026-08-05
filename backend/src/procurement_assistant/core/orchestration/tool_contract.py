"""Scenario Tool 的最小静态接口。"""

from typing import Protocol

from pydantic import BaseModel

from procurement_assistant.core.domain.lifecycle import InputSource
from procurement_assistant.core.protocol.run_input import PageContext


class ScenarioTool(Protocol):
    """一个完整 Scenario Graph 的入口。

    Tool 只创建对应 Graph 的初始 State，不自行调用外围服务或完成采购业务。Tool 描述不
    放在实现类中，而是集中位于 Business 的 ``registry/scenarios.py``，方便开发者一眼
    查看全部可路由能力。
    """

    tool_id: str

    def create_initial_state(
        self,
        *,
        scenario_instance_id: str,
        input_source: InputSource,
        original_user_text: str | None,
        page_context: PageContext,
    ) -> BaseModel:
        """创建一个可交给对应 LangGraph 的初始 State。"""
