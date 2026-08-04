"""智能分流 Scenario Tool。"""

from procurement_assistant.domain.lifecycle import InputSource
from procurement_assistant.orchestration.scenarios.smart_routing.state import SmartRoutingState
from procurement_assistant.protocol.run_input import PageContext


class StartSmartRoutingTool:
    """创建智能分流初始 State，后续步骤全部交给确定性 Graph。"""

    tool_id = "smart_routing"

    def create_initial_state(
        self,
        *,
        scenario_instance_id: str,
        input_source: InputSource,
        original_user_text: str | None,
        page_context: PageContext,
    ) -> SmartRoutingState:
        """把原始文字和页面区域放入 State，不在 Tool 中提取或猜测字段。"""

        return SmartRoutingState(
            scenario_instance_id=scenario_instance_id,
            input_source=input_source,
            original_user_text=original_user_text,
            region_code=page_context.region_code,
        )
