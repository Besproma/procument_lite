"""创建 Core 自己负责的通用等待点。"""

from datetime import datetime, timedelta
from typing import Literal

from procurement_assistant.core.orchestration.actions import (
    CANCEL_SCENE_SWITCH_OPERATION,
    CONFIRM_SCENE_SWITCH_OPERATION,
    RETRY_OPERATION,
    ActionsWaitRequest,
    ConfirmationWaitRequest,
    PendingActionDefinition,
)
from procurement_assistant.core.shared.clock import Clock
from procurement_assistant.core.shared.ids import IdGenerator


class CoreWaitRequestFactory:
    """生成稳定 ID、到期时间以及重试/场景切换等待点。

    Business 的表单和业务按钮工厂复用 ``new_action``、``new_wait_times``；Core 只直接
    创建自己负责的重试与场景切换操作。
    """

    def __init__(self, *, clock: Clock, ids: IdGenerator, ttl_hours: int) -> None:
        self._clock = clock
        self._ids = ids
        self._ttl = timedelta(hours=ttl_hours)

    def new_wait_group_id(self) -> str:
        """创建一个等待组编号。"""

        return self._ids.new("action_group")

    def new_wait_times(self) -> tuple[datetime, datetime]:
        """基于同一个时刻返回创建和过期时间。"""

        created_at = self._clock.now()
        return created_at, created_at + self._ttl

    def new_action(
        self,
        operation: str,
        *,
        label: str,
        schema_id: str,
        style: Literal["primary", "default", "danger"] = "default",
        payload: dict[str, object] | None = None,
    ) -> PendingActionDefinition:
        """为 Core 或 Business 创建不可预测的一次性 Action。"""

        return PendingActionDefinition(
            action_id=self._ids.new("action"),
            kind=operation,
            input_schema_id=schema_id,
            label=label,
            style=style,
            payload=payload or {},
        )

    def retry(self, *, capability: str, empty_schema_id: str) -> ActionsWaitRequest:
        """创建外围服务暂时失败后的用户重试按钮。"""

        created_at, expires_at = self.new_wait_times()
        return ActionsWaitRequest(
            wait_group_id=self.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title=f"{capability}暂时不可用",
            actions=(
                self.new_action(
                    RETRY_OPERATION,
                    label="重试",
                    schema_id=empty_schema_id,
                    style="primary",
                ),
            ),
        )

    def scene_switch(
        self,
        *,
        target_scenario_id: str,
        previous_wait_group_id: str | None,
        original_user_text: str,
        empty_schema_id: str,
    ) -> ConfirmationWaitRequest:
        """创建执行中切换场景的确认和取消按钮。"""

        created_at, expires_at = self.new_wait_times()
        payload: dict[str, object] = {
            "target_scenario_id": target_scenario_id,
            "previous_wait_group_id": previous_wait_group_id,
            "original_user_text": original_user_text,
        }
        return ConfirmationWaitRequest(
            wait_group_id=self.new_wait_group_id(),
            created_at=created_at,
            expires_at=expires_at,
            title="是否中止当前场景并切换到新的场景？",
            target_scenario_id=target_scenario_id,
            previous_wait_group_id=previous_wait_group_id,
            original_user_text=original_user_text,
            actions=(
                self.new_action(
                    CONFIRM_SCENE_SWITCH_OPERATION,
                    label="确认切换",
                    schema_id=empty_schema_id,
                    style="primary",
                    payload=payload,
                ),
                self.new_action(
                    CANCEL_SCENE_SWITCH_OPERATION,
                    label="继续当前场景",
                    schema_id=empty_schema_id,
                    payload=payload,
                ),
            ),
        )
