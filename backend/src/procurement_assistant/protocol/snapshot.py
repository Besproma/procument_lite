"""页面刷新时使用的稳定会话快照。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from procurement_assistant.domain.identifiers import ThreadId
from procurement_assistant.domain.lifecycle import ScenarioStatus
from procurement_assistant.protocol.base import ProtocolModel


class SnapshotMessage(ProtocolModel):
    """允许恢复到界面的历史消息。"""

    message_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class SessionSnapshot(ProtocolModel):
    """前端恢复当前 thread 所需的最小投影。

    ``ui_blocks`` 只保存已经通过采购事件 Schema 校验的可展示块；LangGraph 原始 State、
    Prompt、记忆 JSON 和 Trace 明细永远不进入该响应。
    """

    thread_id: ThreadId
    # 场景 ID 已在启动时通过静态 Catalog 校验。快照只负责通用恢复，不应因为新增 DAG
    # 就修改这一层协议；具体按钮入口仍由 Run 输入协议显式限制。
    scenario_id: str | None = Field(default=None, min_length=1, max_length=100)
    scenario_status: ScenarioStatus | None = None
    messages: tuple[SnapshotMessage, ...] = ()
    ui_blocks: tuple[dict[str, Any], ...] = ()
    checkpoint_expires_at: datetime | None = None


class ErrorResponse(ProtocolModel):
    """SSE 打开前统一使用的安全 JSON 错误。"""

    code: str
    message: str
    trace_id: str
    snapshot_url: str | None = None
    details: dict[str, str] = Field(default_factory=dict)
