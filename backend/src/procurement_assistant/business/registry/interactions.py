"""所有业务 Action 输入模型的一目了然的注册文件。"""

from procurement_assistant.business.interaction.action_inputs import (
    ColumnSelectionInput,
    EmptyActionInput,
    KnowledgeQueryInput,
    PurchaseFieldsFormInput,
    validate_column_selection,
)
from procurement_assistant.core.orchestration.action_registry import (
    ActionInputDefinition,
    ActionInputRegistry,
)

EMPTY_ACTION_SCHEMA_ID = "empty_action"


def build_action_input_registry() -> ActionInputRegistry:
    """显式登记输入模型；新增表单时只需在这里增加一项。"""

    return ActionInputRegistry(
        (
            ActionInputDefinition("purchase_fields_form", PurchaseFieldsFormInput),
            ActionInputDefinition("knowledge_query_form", KnowledgeQueryInput),
            ActionInputDefinition(
                "column_selection",
                ColumnSelectionInput,
                post_validator=validate_column_selection,
            ),
            ActionInputDefinition(EMPTY_ACTION_SCHEMA_ID, EmptyActionInput),
        )
    )
