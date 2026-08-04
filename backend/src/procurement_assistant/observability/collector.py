"""请求局部 Trace 收集器和 span 计时器。"""

import asyncio
import copy
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from types import TracebackType
from typing import Any, Self

from procurement_assistant.observability.models import SpanKind, SpanStatus, TraceSpan
from procurement_assistant.shared.ids import IdGenerator

_CURRENT_PARENT: ContextVar[str | None] = ContextVar("current_trace_parent", default=None)
_CURRENT_COLLECTOR: ContextVar["TraceCollector | None"] = ContextVar(
    "current_trace_collector",
    default=None,
)


_SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "password",
    "database_dsn",
}


def safe_json(value: Any) -> Any:
    """复制并过滤凭据键。

    当前业务字段不做脱敏；这里只删除凭据，因为凭据一旦进入 Trace 就可能被大量只读
    查询和备份权限间接暴露。该函数不改变原对象，避免 Trace 逻辑影响业务 State。
    """

    if isinstance(value, dict):
        return {
            key: safe_json(item)
            for key, item in value.items()
            if str(key).lower().replace("-", "_") not in _SECRET_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    if hasattr(value, "model_dump"):
        return safe_json(value.model_dump(mode="json"))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class TraceCollector:
    """一个 Run 独享的 Trace 收集器。

    不使用跨请求的全局列表；每个请求创建自己的对象，避免并发用户的 span 串线。子 span
    通过 ContextVar 保存父 ID，但只在当前异步任务内生效。
    """

    def __init__(
        self,
        *,
        trace_id: str,
        run_id: str,
        thread_id: str,
        user_id: str,
        ids: IdGenerator,
        clock: Any,
    ) -> None:
        self.trace_id = trace_id
        self.run_id = run_id
        self.thread_id = thread_id
        self.user_id = user_id
        self._ids = ids
        self._clock = clock
        self.spans: list[TraceSpan] = []

    def start_span(
        self,
        *,
        kind: SpanKind,
        name: str,
        target: str | None = None,
        attempt: int = 1,
        input_json: Any = None,
        parent_span_id: str | None = None,
        bind_as_parent: bool = True,
    ) -> "SpanTimer":
        """创建一个尚未开始的异步 span 上下文。

        普通子调用保持 ``bind_as_parent=True``，让其内部 span 自动建立父子关系。HTTP
        根 span 会跨越 StreamingResponse 生命周期，入口协程与流生成协程未必处于同一
        Context，因此根 span 使用 ``False``，再由各执行任务显式 ``parent_scope``。
        """

        return SpanTimer(
            collector=self,
            kind=kind,
            name=name,
            target=target,
            attempt=attempt,
            input_json=input_json,
            parent_span_id=parent_span_id,
            bind_as_parent=bind_as_parent,
        )

    @contextmanager
    def parent_scope(self, span_id: str) -> Iterator[None]:
        """在当前异步任务内把后续 span 绑定到指定父 span。

        ContextVar 会随 ``asyncio.create_task`` 复制，但不会把不同请求串在一起。显式
        scope 也保证任务结束时恢复旧值，防止同一工作线程处理下一请求时沿用旧父 ID。
        """

        parent_token = _CURRENT_PARENT.set(span_id)
        collector_token = _CURRENT_COLLECTOR.set(self)
        try:
            yield
        finally:
            _CURRENT_COLLECTOR.reset(collector_token)
            _CURRENT_PARENT.reset(parent_token)


def current_trace_collector() -> TraceCollector | None:
    """供数据库 Checkpointer 适配器取得当前请求收集器。"""

    return _CURRENT_COLLECTOR.get()


class SpanTimer:
    """异步上下文管理器，保证成功、异常和取消路径都结束 span。"""

    def __init__(
        self,
        *,
        collector: TraceCollector,
        kind: SpanKind,
        name: str,
        target: str | None,
        attempt: int,
        input_json: Any,
        parent_span_id: str | None,
        bind_as_parent: bool,
    ) -> None:
        self.collector = collector
        self.kind = kind
        self.name = name
        self.target = target
        self.attempt = attempt
        self.input_json = safe_json(input_json)
        self.parent_span_id = parent_span_id
        self.bind_as_parent = bind_as_parent
        self.span: TraceSpan | None = None
        self._started_monotonic = 0.0
        self._parent_token: Any = None

    async def __aenter__(self) -> Self:
        """记录开始时间并建立当前异步任务的父 span。"""

        started_at = self.collector._clock.now()
        span_id = self.collector._ids.new("span")
        parent = self.parent_span_id or _CURRENT_PARENT.get()
        self.span = TraceSpan(
            trace_id=self.collector.trace_id,
            span_id=span_id,
            parent_span_id=parent,
            run_id=self.collector.run_id,
            thread_id=self.collector.thread_id,
            user_id=self.collector.user_id,
            kind=self.kind,
            name=self.name,
            target=self.target,
            attempt=self.attempt,
            started_at=started_at,
            input_json=copy.deepcopy(self.input_json),
        )
        self.collector.spans.append(self.span)
        self._started_monotonic = monotonic()
        if self.bind_as_parent:
            self._parent_token = _CURRENT_PARENT.set(span_id)
        return self

    def set_output(self, value: Any) -> None:
        """保存经过凭据过滤的输出副本，不影响原业务对象。"""

        if self.span is None:
            raise RuntimeError("span 尚未开始")
        self.span.output_json = copy.deepcopy(safe_json(value))

    def mark_first_byte(self) -> None:
        """记录流式调用第一次产生可传输数据的相对耗时。"""

        if self.span is not None and self.span.first_byte_ms is None:
            self.span.first_byte_ms = (monotonic() - self._started_monotonic) * 1000

    def mark_first_text_delta(self) -> None:
        """记录第一段可展示文字的相对耗时，同时也视为首字节。"""

        self.mark_first_byte()
        if self.span is not None and self.span.first_text_delta_ms is None:
            self.span.first_text_delta_ms = (monotonic() - self._started_monotonic) * 1000

    def mark_final_result(self) -> None:
        """记录结构化最终结果到达时间。"""

        if self.span is not None and self.span.final_result_ms is None:
            self.span.final_result_ms = (monotonic() - self._started_monotonic) * 1000

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """结束 span，保留异常让上层决定业务分支。"""

        del traceback
        assert self.span is not None
        finished_at = self.collector._clock.now()
        status = SpanStatus.OK
        error_code: str | None = None
        if exc_type is not None:
            status = (
                SpanStatus.CANCELLED if exc_type is asyncio.CancelledError else SpanStatus.ERROR
            )
            error_code = getattr(exc_value, "code", exc_type.__name__)
        self.span.status = status
        self.span.error_code = error_code
        self.span.finished_at = finished_at
        self.span.duration_ms = (monotonic() - self._started_monotonic) * 1000
        if self._parent_token is not None:
            _CURRENT_PARENT.reset(self._parent_token)
