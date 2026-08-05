"""Core 交给 LangGraph interrupt 节点的可信恢复值。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GraphResumeInput(BaseModel):
    """Action 已在 HTTP 入口校验并消费后的统一恢复数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    values: dict[str, Any] = Field(default_factory=dict)
