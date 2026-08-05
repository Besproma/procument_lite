"""创建采购业务专属的表单、选项和按钮等待点。"""

from procurement_assistant.business.domain.procurement import ColumnCandidate
from procurement_assistant.business.interaction.operations import BusinessActionOperation
from procurement_assistant.core.orchestration.actions import (
    ActionsWaitRequest,
    FormWaitRequest,
    OptionDefinition,
    OptionsWaitRequest,
)
from procurement_assistant.core.orchestration.wait_factory import CoreWaitRequestFactory
from procurement_assistant.core.protocol.events import FormField, FormFieldType


class BusinessWaitRequestFactory:
    """使用 Core 的 ID/有效期机制创建采购业务等待内容。

    Core 负责 Action 的生命周期和安全编号；本类只决定采购场景要显示哪些字段、按钮
    和文案。未来新增业务等待点时不会修改 Core。
    """

    def __init__(self, core: CoreWaitRequestFactory) -> None:
        self._core = core

    def purchase_fields(self, missing_fields: tuple[str, ...]) -> FormWaitRequest:
        """根据当前真正缺失的字段创建采购信息表单。"""

        field_definitions = {
            "productName": FormField(
                field_id="productName",
                label="商品名称",
                type=FormFieldType.TEXT,
                required=True,
                max_length=500,
            ),
            "purchasePurpose": FormField(
                field_id="purchasePurpose",
                label="采购用途",
                type=FormFieldType.TEXT,
                required=True,
                max_length=500,
            ),
            "budgetAmount": FormField(
                field_id="budgetAmount",
                label="预算金额",
                type=FormFieldType.NUMBER,
                required=True,
                min=0,
            ),
            "regionCode": FormField(
                field_id="regionCode",
                label="区域编码",
                type=FormFieldType.TEXT,
                required=True,
                max_length=64,
            ),
        }
        created_at, expires_at = self._core.new_wait_times()
        return FormWaitRequest(
            wait_group_id=self._core.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title="请补充采购信息",
            action=self._core.new_action(
                BusinessActionOperation.SUBMIT_FORM,
                label="继续",
                schema_id="purchase_fields_form",
                style="primary",
            ),
            fields=tuple(field_definitions[field] for field in missing_fields),
        )

    def knowledge_query(self) -> FormWaitRequest:
        """创建知识 key 输入表单。"""

        created_at, expires_at = self._core.new_wait_times()
        return FormWaitRequest(
            wait_group_id=self._core.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title="请输入要查询的采购知识",
            action=self._core.new_action(
                BusinessActionOperation.SUBMIT_FORM,
                label="查询",
                schema_id="knowledge_query_form",
                style="primary",
            ),
            fields=(
                FormField(
                    field_id="queryText",
                    label="查询内容",
                    type=FormFieldType.TEXT,
                    required=True,
                    max_length=1000,
                ),
            ),
            submit_label="查询",
        )

    def column_selection(self, candidates: tuple[ColumnCandidate, ...]) -> OptionsWaitRequest:
        """把一次栏目调用返回的全部候选转换成单选等待点。"""

        created_at, expires_at = self._core.new_wait_times()
        return OptionsWaitRequest(
            wait_group_id=self._core.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title="请选择采购栏目",
            action=self._core.new_action(
                BusinessActionOperation.SELECT_OPTION,
                label="确认栏目",
                schema_id="column_selection",
                style="primary",
                payload={"option_ids": [candidate.option_id for candidate in candidates]},
            ),
            options=tuple(
                OptionDefinition(
                    option_id=candidate.option_id,
                    label=candidate.column_name,
                    description=candidate.category_name,
                )
                for candidate in candidates
            ),
        )

    def recommendation_actions(self, *, has_next: bool) -> ActionsWaitRequest:
        """创建商品推荐阶段仍可继续使用的操作。"""

        actions = []
        if has_next:
            actions.append(
                self._core.new_action(
                    BusinessActionOperation.NEXT_PAGE,
                    label="换一批",
                    schema_id="empty_action",
                )
            )
        actions.extend(
            (
                self._core.new_action(
                    BusinessActionOperation.APPEND_PRODUCT,
                    label="追加其他商品",
                    schema_id="empty_action",
                ),
                self._core.new_action(
                    BusinessActionOperation.OTHER_PROCUREMENT_MODE,
                    label="没有满意的商品，请为我推荐另外的采购方式",
                    schema_id="empty_action",
                ),
                self._core.new_action(
                    BusinessActionOperation.END_RECOMMENDATION,
                    label="结束本次推荐",
                    schema_id="empty_action",
                ),
            )
        )
        created_at, expires_at = self._core.new_wait_times()
        return ActionsWaitRequest(
            wait_group_id=self._core.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title="你还可以",
            actions=tuple(actions),
        )

    def single_navigation_action(
        self,
        operation: BusinessActionOperation,
        *,
        title: str,
        label: str,
    ) -> ActionsWaitRequest:
        """创建自行采购或自定义采购的单按钮等待点。"""

        created_at, expires_at = self._core.new_wait_times()
        return ActionsWaitRequest(
            wait_group_id=self._core.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title=title,
            actions=(
                self._core.new_action(
                    operation,
                    label=label,
                    schema_id="empty_action",
                    style="primary",
                ),
            ),
        )
