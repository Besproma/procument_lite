"""LangGraph 运行时上下文和 Delegate 调用治理。"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from procurement_assistant.config import AppSettings
from procurement_assistant.delegates.common.call_context import (
    DelegateCallContext,
    RunDeadline,
)
from procurement_assistant.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.domain.errors import (
    DelegateTimeoutError,
    NonRetryableDelegateError,
    ProcurementAssistantError,
    RetryableDelegateError,
)
from procurement_assistant.observability.collector import TraceCollector
from procurement_assistant.observability.models import SpanKind
from procurement_assistant.protocol.emitter import AGUIEventEmitter
from procurement_assistant.protocol.run_input import PageContext
from procurement_assistant.shared.clock import Clock
from procurement_assistant.shared.ids import IdGenerator

ResultT = TypeVar("ResultT")
DelegateOperation = Callable[[DelegateCallContext, AgentStreamSink | None], Awaitable[ResultT]]
DatabaseOperation = Callable[[], Awaitable[ResultT]]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """一次 Run 的临时上下文。

    该对象通过 LangGraph 的 runtime context 传递，永远不写进 Checkpoint。它包含事件发送
    器、Trace 和 Delegate 期限，但不包含业务 State 或数据库连接。
    """

    user_id: str
    thread_id: str
    run_id: str
    trace_id: str
    page_context: PageContext
    deadline: RunDeadline
    trace: TraceCollector
    events: AGUIEventEmitter
    clock: Clock
    ids: IdGenerator

    async def call_database(
        self,
        *,
        name: str,
        operation: DatabaseOperation[ResultT],
        input_data: Any = None,
    ) -> ResultT:
        """执行一个有业务含义的数据库 Delegate 方法并记录独立 span。

        数据库调用不套用外围 Agent 的 15 秒重试策略：入口幂等、Action 消费和状态更新
        可能包含写操作，不能在不知道事务结果的情况下由通用层盲目重放。数据库连接和
        statement 超时由生产 Database Delegate 自己配置。
        """

        async with self.trace.start_span(
            kind=SpanKind.DATABASE,
            name=name,
            target=name,
            input_json=input_data,
        ) as span:
            result = await operation()
            span.set_output(result)
            return result

    async def call_delegate(
        self,
        *,
        name: str,
        kind: SpanKind,
        operation: DelegateOperation[ResultT],
        settings: AppSettings,
        expose_stream_to_ui: bool = False,
        input_data: Any = None,
    ) -> ResultT:
        """统一执行一次外围调用、超时、重试、Trace 和可选流转发。

        总 Run 截止时间由 ``self.deadline`` 控制；每次尝试最多使用配置的 15 秒或剩余时间
        中较小者。只有明确的临时错误和超时会重试一次，业务错误与结构化协议错误直接
        抛出，避免把同一个不可重试请求重复发送给外围服务。
        """

        last_error: ProcurementAssistantError | None = None
        for attempt in range(1, settings.delegate_max_attempts + 1):
            self.deadline.ensure_remaining()
            timeout_seconds = min(
                settings.delegate_attempt_timeout_seconds,
                self.deadline.remaining_seconds,
            )
            if timeout_seconds <= 0:
                self.deadline.ensure_remaining()

            try:
                # try/except 必须放在 span 上下文外层。若在 ``async with`` 内吞掉第一
                # 次失败再重试，计时器看不到异常，会把失败尝试错误记录成 OK。
                async with self.trace.start_span(
                    kind=kind,
                    name=name,
                    target=name,
                    attempt=attempt,
                    input_json=input_data,
                ) as span:
                    assert span.span is not None
                    call_context = DelegateCallContext(
                        trace_id=self.trace_id,
                        parent_span_id=span.span.span_id,
                        run_id=self.run_id,
                        deadline=self.deadline,
                        attempt=attempt,
                    )

                    async def stream_sink(event: Any) -> None:
                        """记录流耗时，并只转发明确允许展示的内容。"""

                        span.mark_first_byte()
                        if getattr(event, "kind", None) == "text_delta":
                            span.mark_first_text_delta()
                        if expose_stream_to_ui:
                            await self.events.agent_stream(event)

                    try:
                        async with asyncio.timeout(timeout_seconds):
                            result = await operation(
                                call_context,
                                # 即使 UI 展示关闭也提供内部 sink，用于记录外围流的首字节
                                # 和首段文字耗时；sink 会阻止未获批准的内容进入前端。
                                stream_sink,
                            )
                    except TimeoutError as exc:
                        # 在离开 span 之前换成稳定领域错误，使本次失败尝试的 error_code
                        # 记录为 DELEGATE_TIMEOUT，而不是依赖 Python 的异常类名称。
                        raise DelegateTimeoutError(f"{name} 调用超时") from exc
                    span.mark_final_result()
                    span.set_output(result)
                    return result
            except DelegateTimeoutError as exc:
                last_error = exc
                if attempt >= settings.delegate_max_attempts:
                    raise
            except RetryableDelegateError as exc:
                last_error = exc
                if attempt >= settings.delegate_max_attempts:
                    raise
            except NonRetryableDelegateError:
                raise

        # 循环必定在 return 或 raise 中结束；这个保护让类型检查器知道不会返回 None。
        assert last_error is not None
        raise last_error
