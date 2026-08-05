"""知识推荐 Scenario Tool。"""

from procurement_assistant.business.scenarios.knowledge.state import KnowledgeState
from procurement_assistant.core.domain.lifecycle import InputSource
from procurement_assistant.core.protocol.run_input import PageContext


class StartKnowledgeRecommendationTool:
    """创建知识推荐初始 State。"""

    tool_id = "knowledge_recommendation"

    def create_initial_state(
        self,
        *,
        scenario_instance_id: str,
        input_source: InputSource,
        original_user_text: str | None,
        page_context: PageContext,
    ) -> KnowledgeState:
        """自然语言原文直接成为精确匹配 key；按钮进入时保持为空并显示表单。"""

        del page_context
        return KnowledgeState(
            scenario_instance_id=scenario_instance_id,
            input_source=input_source,
            query_text=original_user_text,
        )
