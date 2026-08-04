"""智能分流 Graph State。"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from procurement_assistant.domain.lifecycle import InputSource, ScenarioStatus
from procurement_assistant.domain.procurement import ColumnCandidate, NavigationTarget
from procurement_assistant.orchestration.actions import ActionOperation, WaitRequest
from procurement_assistant.orchestration.models import RecoverableError
from procurement_assistant.orchestration.subgraphs.product_recommendation.state import (
    RecommendationState,
)


class SmartRoutingState(BaseModel):
    """智能分流在节点之间和跨 Turn 保存的全部业务数据。

    这里只保存恢复流程必需的已校验数据。Delegate、数据库连接、事件发送器和 Trace 等
    运行时对象由 ``ExecutionContext`` 提供，绝不能写入 Checkpoint。
    """

    model_config = ConfigDict(extra="forbid")

    scenario_instance_id: str
    status: ScenarioStatus = ScenarioStatus.RUNNING
    input_source: InputSource
    original_user_text: str | None = None
    item_sequence: int = Field(default=1, ge=1)

    product_name: str | None = None
    purchase_purpose: str | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    region_code: str | None = None

    is_ioi: bool | None = None
    column_candidates: tuple[ColumnCandidate, ...] = ()
    selected_column: ColumnCandidate | None = None
    recommendation: RecommendationState | None = None
    duplicate_self_purchase: bool | None = None
    entered_custom_purchase: bool = False
    queue_count: int | None = Field(default=None, ge=0)
    navigation_target: NavigationTarget | None = None

    wait_request: WaitRequest | None = None
    selected_action: ActionOperation | None = None
    recoverable_error: RecoverableError | None = None

    @property
    def missing_required_fields(self) -> tuple[str, ...]:
        """按前端字段 ID 返回仍需用户补充的必填项。"""

        missing: list[str] = []
        if self.product_name is None:
            missing.append("productName")
        if self.purchase_purpose is None:
            missing.append("purchasePurpose")
        if self.budget_amount is None:
            missing.append("budgetAmount")
        if self.region_code is None:
            missing.append("regionCode")
        return tuple(missing)
