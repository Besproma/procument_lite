"""业务层可使用的数据库能力接口。

接口只暴露带业务含义的方法，不提供任意 ``execute(sql)``。这样 Graph 和 API 无法绕过
归属校验、短事务和状态约束直接操作数据库。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from procurement_assistant.domain.lifecycle import (
    ActionStatus,
    InputSource,
    RunStatus,
    ScenarioStatus,
)
from procurement_assistant.orchestration.actions import WaitRequest


class DatabaseRecord(BaseModel):
    """不可变数据库记录基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ThreadRecord(DatabaseRecord):
    """一个前端会话及其当前活动场景。"""

    thread_id: str
    user_id: str
    active_scenario_instance_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ScenarioRecord(DatabaseRecord):
    """跨多个 Run 的场景实例。"""

    scenario_instance_id: str
    thread_id: str
    user_id: str
    scenario_id: str
    input_source: InputSource
    status: ScenarioStatus
    started_at: datetime
    updated_at: datetime
    expires_at: datetime
    current_wait_group_id: str | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None


class RunRecord(DatabaseRecord):
    """用于幂等和审计的一次 Run。"""

    run_id: str
    thread_id: str
    user_id: str
    trace_id: str
    input_type: str
    scenario_instance_id: str | None = None
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None


class ActionRecord(DatabaseRecord):
    """数据库中的一次性 Action。"""

    action_id: str
    wait_group_id: str
    thread_id: str
    user_id: str
    scenario_instance_id: str
    kind: str
    input_schema_id: str
    status: ActionStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    consumed_by_run_id: str | None = None


class MessageRecord(DatabaseRecord):
    """可恢复到前端的用户或助手消息。"""

    message_id: str
    thread_id: str
    user_id: str
    run_id: str
    role: str
    content: str
    created_at: datetime


class AdmissionStatus(StrEnum):
    """入口短事务对本次 Run 的决定。"""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    THREAD_BUSY = "thread_busy"


class BeginRunRequest(DatabaseRecord):
    """原子登记 Run、获取租约和可选消费 Action 的输入。"""

    run_id: str
    thread_id: str
    user_id: str
    trace_id: str
    input_type: str
    lease_seconds: float = Field(gt=0)
    action_id: str | None = None


class RunAdmission(DatabaseRecord):
    """入口短事务的结果。"""

    status: AdmissionStatus
    run: RunRecord
    consumed_action: ActionRecord | None = None


class DatabaseDelegate(Protocol):
    """会话、Run、Action、消息、租约和记忆的数据库边界。"""

    async def begin_run(self, request: BeginRunRequest) -> RunAdmission:
        """用一个短事务执行幂等、租约和 Action 消费。"""

    async def get_run(self, run_id: str, user_id: str, thread_id: str) -> RunRecord | None:
        """读取已有 Run 供入口在预校验前保持 runId 幂等优先级。"""

    async def finish_run(
        self, run_id: str, status: RunStatus, error_code: str | None = None
    ) -> None:
        """更新 Run 终态并释放其 thread 租约。"""

    async def bind_run_to_scenario(self, run_id: str, scenario_instance_id: str) -> None:
        """新场景创建后把入口 Run 关联到场景实例。"""

    async def get_or_create_thread(self, user_id: str, thread_id: str) -> ThreadRecord:
        """取得当前用户的 thread，不允许跨用户复用 ID。"""

    async def get_thread(self, user_id: str, thread_id: str) -> ThreadRecord | None:
        """只读取得 thread；不存在时不得为了快照查询而创建空会话。"""

    async def get_action(
        self,
        action_id: str,
        user_id: str,
        thread_id: str,
    ) -> ActionRecord:
        """读取 Action 的输入 Schema，并校验用户与会话归属。

        入口先用它做纯校验，确认用户填写值合法后才调用 ``begin_run`` 消费 Action。
        读取与最终消费之间允许出现竞态；最终消费事务仍必须再次锁定和校验，不能把这次
        预读取当作授权凭证。
        """

    async def start_scenario(self, scenario: ScenarioRecord) -> None:
        """创建场景并设置为 thread 的唯一活动场景。"""

    async def get_active_scenario(self, user_id: str, thread_id: str) -> ScenarioRecord | None:
        """返回当前未终止场景，过期场景按实现规则转为 expired。"""

    async def update_scenario_status(
        self,
        scenario_instance_id: str,
        status: ScenarioStatus,
        reason: str | None = None,
    ) -> None:
        """更新场景生命周期，并在终态使旧 Action 失效。"""

    async def expire_active_scenarios(self, reason: str) -> int:
        """把部署前仍活动的场景统一标记为 expired，并返回处理数量。

        这是发布脚本使用的管理能力，不由普通用户请求调用。它仍然必须走 Database
        Delegate，才能和正常状态变更共用锁、Action 失效及活动指针清理规则；脚本不能
        在命令行里拼接 SQL 或只更新其中一张表。
        """

    async def save_wait_request(
        self,
        *,
        user_id: str,
        thread_id: str,
        scenario_instance_id: str,
        wait_request: WaitRequest,
    ) -> None:
        """按 Checkpoint 中预生成的 ID 幂等保存一组 Action。"""

    async def set_current_wait_group(
        self,
        scenario_instance_id: str,
        wait_group_id: str | None,
    ) -> None:
        """切换确认取消时恢复原等待组，终态时可清空。"""

    async def append_message(self, message: MessageRecord) -> None:
        """持久化一条用户或可展示助手消息。"""

    async def list_messages(self, user_id: str, thread_id: str) -> tuple[MessageRecord, ...]:
        """按创建顺序返回当前 thread 的消息。"""

    async def append_ui_block(self, user_id: str, thread_id: str, block: dict[str, Any]) -> None:
        """保存已经校验、可用于页面刷新的采购 UI 块。"""

    async def list_ui_blocks(self, user_id: str, thread_id: str) -> tuple[dict[str, Any], ...]:
        """返回当前 thread 的可展示 UI 块。"""

    async def load_memory(self, user_id: str) -> dict[str, Any]:
        """读取一个用户的完整个人记忆 JSON。"""

    async def merge_memory(
        self,
        user_id: str,
        updates: dict[str, Any],
        remove_keys: tuple[str, ...],
        source_run_id: str,
    ) -> None:
        """在短事务中把补丁合并到当时最新记忆。"""
