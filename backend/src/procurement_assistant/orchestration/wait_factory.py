"""集中创建可持久化 WaitRequest。"""

from datetime import datetime, timedelta
from typing import Literal

from procurement_assistant.domain.procurement import ColumnCandidate
from procurement_assistant.orchestration.actions import (
    ActionOperation,
    ActionsWaitRequest,
    ConfirmationWaitRequest,
    FormWaitRequest,
    OptionDefinition,
    OptionsWaitRequest,
    PendingActionDefinition,
)
from procurement_assistant.protocol.events import FormField, FormFieldType
from procurement_assistant.shared.clock import Clock
from procurement_assistant.shared.ids import IdGenerator


class WaitRequestFactory:
    """为所有等待点生成稳定 group/action ID 和 24 小时到期时间。

    工厂在进入 ``interrupt`` 的前一个节点调用，生成结果先写入 Checkpoint。恢复时
    LangGraph 会重新执行 interrupt 节点，但不会重新生成 ID，因此数据库可以安全幂等 upsert。
    """

    def __init__(self, *, clock: Clock, ids: IdGenerator, ttl_hours: int) -> None:
        self._clock = clock
        self._ids = ids
        self._ttl = timedelta(hours=ttl_hours)

    def _times(self) -> tuple[datetime, datetime]:
        """返回同一时刻计算的创建与到期时间。"""

        created_at = self._clock.now()
        return created_at, created_at + self._ttl

    def _action(
        self,
        operation: ActionOperation,
        *,
        label: str,
        schema_id: str = "empty_action",
        style: Literal["primary", "default", "danger"] = "default",
        payload: dict[str, object] | None = None,
    ) -> PendingActionDefinition:
        """创建一个不可预测的一次性 Action 定义。"""

        return PendingActionDefinition(
            action_id=self._ids.new("action"),
            kind=operation,
            input_schema_id=schema_id,
            label=label,
            style=style,
            payload=payload or {},
        )

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
        created_at, expires_at = self._times()
        return FormWaitRequest(
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title="请补充采购信息",
            action=self._action(
                ActionOperation.SUBMIT_FORM,
                label="继续",
                schema_id="purchase_fields_form",
                style="primary",
            ),
            fields=tuple(field_definitions[field] for field in missing_fields),
        )

    def knowledge_query(self) -> FormWaitRequest:
        """创建知识 key 输入表单。"""

        created_at, expires_at = self._times()
        return FormWaitRequest(
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title="请输入要查询的采购知识",
            action=self._action(
                ActionOperation.SUBMIT_FORM,
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
        """把一次栏目调用的全部候选转换成单选等待点。"""

        created_at, expires_at = self._times()
        return OptionsWaitRequest(
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title="请选择采购栏目",
            action=self._action(
                ActionOperation.SELECT_OPTION,
                label="确认栏目",
                schema_id="column_selection",
                style="primary",
                payload={
                    "option_ids": [candidate.option_id for candidate in candidates],
                },
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

        actions: list[PendingActionDefinition] = []
        if has_next:
            actions.append(self._action(ActionOperation.NEXT_PAGE, label="换一批"))
        actions.extend(
            (
                self._action(ActionOperation.APPEND_PRODUCT, label="追加其他商品"),
                self._action(
                    ActionOperation.OTHER_PROCUREMENT_MODE,
                    label="没有满意的商品，请为我推荐另外的采购方式",
                ),
                self._action(ActionOperation.END_RECOMMENDATION, label="结束本次推荐"),
            )
        )
        created_at, expires_at = self._times()
        return ActionsWaitRequest(
            kind="actions",
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title="你还可以",
            actions=tuple(actions),
        )

    def single_navigation_action(
        self,
        operation: ActionOperation,
        *,
        title: str,
        label: str,
    ) -> ActionsWaitRequest:
        """创建自行采购或自定义采购的单按钮等待点。"""

        created_at, expires_at = self._times()
        return ActionsWaitRequest(
            kind="actions",
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title=title,
            actions=(self._action(operation, label=label, style="primary"),),
        )

    def retry(self, *, capability: str) -> ActionsWaitRequest:
        """为最后成功 Checkpoint 创建一次性重试 Action。"""

        created_at, expires_at = self._times()
        return ActionsWaitRequest(
            kind="actions",
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title=f"{capability}暂时不可用",
            actions=(self._action(ActionOperation.RETRY, label="重试", style="primary"),),
        )

    def scene_switch(
        self,
        *,
        target_scenario_id: str,
        previous_wait_group_id: str | None,
        original_user_text: str,
    ) -> ConfirmationWaitRequest:
        """创建执行中切换场景的确认与取消操作。"""

        created_at, expires_at = self._times()
        shared_payload: dict[str, object] = {
            "target_scenario_id": target_scenario_id,
            "previous_wait_group_id": previous_wait_group_id,
            "original_user_text": original_user_text,
        }
        return ConfirmationWaitRequest(
            wait_group_id=self._ids.new("action_group"),
            created_at=created_at,
            expires_at=expires_at,
            title="是否中止当前场景并切换到新的场景？",
            target_scenario_id=target_scenario_id,
            previous_wait_group_id=previous_wait_group_id,
            original_user_text=original_user_text,
            actions=(
                self._action(
                    ActionOperation.CONFIRM_SCENE_SWITCH,
                    label="确认切换",
                    style="primary",
                    payload=shared_payload,
                ),
                self._action(
                    ActionOperation.CANCEL_SCENE_SWITCH,
                    label="继续当前场景",
                    payload=shared_payload,
                ),
            ),
        )
