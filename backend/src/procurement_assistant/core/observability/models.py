"""Trace span 数据模型。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SpanKind(StrEnum):
    """调用链中的可查询层级。"""

    HTTP = "HTTP"
    REACT = "REACT"
    SCENARIO = "SCENARIO"
    GRAPH = "GRAPH"
    NODE = "NODE"
    MODEL = "MODEL"
    AGENT = "AGENT"
    SERVICE = "SERVICE"
    DATABASE = "DATABASE"
    MEMORY = "MEMORY"


class SpanStatus(StrEnum):
    """Span 结果。"""

    RUNNING = "RUNNING"
    OK = "OK"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class TraceSpan(BaseModel):
    """一个步骤最终要写入数据库的耗时记录。

    ``span_id`` 是当前步骤编号，``parent_span_id`` 指向上一级步骤。根 Span 的
    parent_span_id 为空；把所有记录按这两个字段连接起来，就能看到完整调用树。

    输入输出按当前确认的“不脱敏业务数据”规则保存，但 ``safe_json`` 会在边界排除
    Authorization、Cookie、API Key 和数据库口令，避免把凭据写入 Trace。
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    run_id: str
    thread_id: str
    user_id: str
    kind: SpanKind
    name: str
    target: str | None = None
    attempt: int = Field(default=1, ge=1)
    status: SpanStatus = SpanStatus.RUNNING
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None
    first_byte_ms: float | None = None
    first_text_delta_ms: float | None = None
    final_result_ms: float | None = None
    input_json: Any = None
    output_json: Any = None
    error_code: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
