"""外围 Agent 原始流映射后的内部事件。"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentStreamEvent(BaseModel):
    """统一的外围流事件。

    ``final_result`` 只在 Delegate 内部消费和校验，发送前端时仅允许 progress、
    text_delta 和 status。隐藏推理、凭据和原始异常没有对应字段，无法被误转发。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    delegate_id: str
    attempt: int = Field(ge=1, le=2)
    sequence: int = Field(ge=1)
    kind: Literal["progress", "text_delta", "status", "final_result", "error"]
    display_text: str | None = None
    final_result: dict[str, Any] | None = None
    error_code: str | None = None


AgentStreamSink = Callable[[AgentStreamEvent], Awaitable[None]]
