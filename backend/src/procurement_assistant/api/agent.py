"""``POST /api/v1/agent`` 的入口、SSE 和完整收尾。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from procurement_assistant.api.dependencies import get_user_id
from procurement_assistant.api.errors import error_response
from procurement_assistant.api.runtime import APIRuntime
from procurement_assistant.api.sse import encode_sse_event
from procurement_assistant.delegates.common.call_context import RunDeadline
from procurement_assistant.domain.errors import (
    ProcurementAssistantError,
    ServiceOverloadedError,
)
from procurement_assistant.memory.updater import MemoryUpdateRequest
from procurement_assistant.observability.collector import TraceCollector
from procurement_assistant.observability.models import SpanKind
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.protocol.emitter import AGUIEventEmitter
from procurement_assistant.protocol.events import TextMessageContentEvent
from procurement_assistant.protocol.run_input import RunAgentInput

_END_OF_STREAM = object()
_LOGGER = logging.getLogger(__name__)


class _SafeInternalError(ProcurementAssistantError):
    """只在入口尚未打开 SSE 时使用的固定内部错误。"""

    code = "INTERNAL_ERROR"


def build_agent_router(runtime: APIRuntime) -> APIRouter:
    """创建 Agent 路由；采购业务本身仍全部位于 Application/Graph。"""

    router = APIRouter(prefix="/api/v1", tags=["agent"])

    @router.post("/agent")
    async def run_agent(
        http_request: Request,
        run_input: RunAgentInput,
        user_id: Annotated[str, Depends(get_user_id)],
    ) -> Response:
        trace_id = http_request.state.trace_id
        collector = TraceCollector(
            trace_id=trace_id,
            run_id=run_input.run_id,
            thread_id=run_input.thread_id,
            user_id=user_id,
            ids=runtime.ids,
            clock=runtime.clock,
        )
        root_span = collector.start_span(
            kind=SpanKind.HTTP,
            name="http.post_agent",
            target="POST /api/v1/agent",
            input_json=run_input,
            # 根 span 跨路由函数和 StreamingResponse 生成器，不能把 ContextVar token
            # 绑定在一个协程后从另一个协程 reset，子任务改用显式 parent_scope。
            bind_as_parent=False,
        )
        await root_span.__aenter__()
        if root_span.span is None:
            raise RuntimeError("HTTP 根 span 未正确启动")
        root_span_id = root_span.span.span_id

        capacity_acquired = await runtime.capacity.try_acquire()
        if not capacity_acquired:
            error = ServiceOverloadedError("系统当前请求较多，请稍后重试")
            await root_span.__aexit__(type(error), error, None)
            await runtime.trace_flusher.flush(collector)
            return error_response(error, trace_id=trace_id)

        try:
            # admission 是 SSE 之前的短事务：原子处理 runId 幂等、thread 租约和可选
            # Action 消费。它成功后才允许返回 HTTP 200 StreamingResponse。
            with collector.parent_scope(root_span_id):
                async with collector.start_span(
                    kind=SpanKind.DATABASE,
                    name="database.run.begin",
                    target="run_admission",
                    input_json={
                        "run_id": run_input.run_id,
                        "thread_id": run_input.thread_id,
                        "input_type": (
                            run_input.forwarded_props.procurement_input.type
                            if run_input.forwarded_props.procurement_input is not None
                            else "natural_language"
                        ),
                    },
                ) as admission_span:
                    admission = await runtime.application.admit(
                        user_id=user_id,
                        request=run_input,
                        trace_id=trace_id,
                    )
                    admission_span.set_output(admission)
        except ProcurementAssistantError as error:
            await runtime.capacity.release()
            await root_span.__aexit__(type(error), error, None)
            await runtime.trace_flusher.flush(collector)
            return error_response(
                error,
                trace_id=trace_id,
                thread_id=run_input.thread_id,
            )
        except Exception as error:
            await runtime.capacity.release()
            await root_span.__aexit__(type(error), error, None)
            await runtime.trace_flusher.flush(collector)
            _LOGGER.exception("Run 入口登记发生未知异常，trace_id=%s", trace_id)
            return error_response(
                _SafeInternalError("系统暂时无法处理，请稍后重试"),
                trace_id=trace_id,
            )

        queue: asyncio.Queue[BaseModel | object] = asyncio.Queue()

        async def event_sink(event: BaseModel) -> None:
            """发射器只入无界请求局部队列，不在业务节点中直接操作 ASGI socket。"""

            await queue.put(event)

        emitter = AGUIEventEmitter(
            thread_id=run_input.thread_id,
            run_id=run_input.run_id,
            sink=event_sink,
        )
        execution_context = ExecutionContext(
            user_id=user_id,
            thread_id=run_input.thread_id,
            run_id=run_input.run_id,
            trace_id=trace_id,
            page_context=run_input.forwarded_props.page_context,
            deadline=RunDeadline.after(runtime.settings.run_deadline_seconds),
            trace=collector,
            events=emitter,
            clock=runtime.clock,
            ids=runtime.ids,
        )
        result_holder: list[Any] = []
        execution_errors: list[BaseException] = []

        async def execute_application() -> None:
            """在独立任务中执行 Graph，让生成器可同时消费并发送事件。"""

            try:
                with collector.parent_scope(root_span_id):
                    result = await runtime.application.execute(
                        user_id=user_id,
                        request=run_input,
                        admission=admission,
                        context=execution_context,
                    )
                result_holder.append(result)
            except asyncio.CancelledError as error:
                execution_errors.append(error)
                raise
            except ProcurementAssistantError as error:
                # Application 已经发送安全 RUN_ERROR 并结束 Run；这里不让异常越过
                # StreamingResponse，否则 ASGI 会在已经写出 200 后再打印协议错误。
                execution_errors.append(error)
            except Exception as error:
                execution_errors.append(error)
                _LOGGER.exception("Run 执行发生未知异常，trace_id=%s", trace_id)
            finally:
                await queue.put(_END_OF_STREAM)

        async def stream_events() -> AsyncIterator[bytes]:
            """逐条输出 AG-UI 事件，并在断线、成功和失败路径统一收尾。"""

            producer = asyncio.create_task(
                execute_application(),
                name=f"agent-run-{run_input.run_id}",
            )
            stream_error: BaseException | None = None
            try:
                while True:
                    event = await queue.get()
                    if event is _END_OF_STREAM:
                        break
                    if not isinstance(event, BaseModel):
                        raise RuntimeError("SSE 队列包含未校验事件")
                    root_span.mark_first_byte()
                    if isinstance(event, TextMessageContentEvent):
                        root_span.mark_first_text_delta()
                    yield encode_sse_event(event)

                await producer
                if result_holder:
                    result = result_holder[0]
                    root_span.mark_final_result()
                    root_span.set_output(
                        {
                            "event_count": len(emitter.events),
                            "assistant_text_count": len(result.assistant_texts),
                            "graph_status": (
                                result.graph_result.status
                                if result.graph_result is not None
                                else None
                            ),
                        }
                    )
                    # 生成器只有在上一帧已经交给 ASGI 后才继续执行到这里，因此此时
                    # RUN_FINISHED 已完成网络侧发送，可以启动不阻塞响应的记忆任务。
                    runtime.background_tasks.start(
                        runtime.memory_updater.update(
                            MemoryUpdateRequest(
                                user_id=user_id,
                                thread_id=run_input.thread_id,
                                run_id=run_input.run_id,
                                trace_id=trace_id,
                                parent_span_id=root_span_id,
                                turn_input=run_input.model_dump(mode="json", by_alias=True),
                                assistant_texts=result.assistant_texts,
                            )
                        ),
                        name=f"memory-update-{run_input.run_id}",
                    )
            except BaseException as error:
                stream_error = error
                raise
            finally:
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
                final_error = stream_error or (execution_errors[0] if execution_errors else None)
                await root_span.__aexit__(
                    type(final_error) if final_error is not None else None,
                    final_error,
                    None,
                )
                await runtime.capacity.release()
                await runtime.trace_flusher.flush(collector)

        return StreamingResponse(
            stream_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
                "X-Trace-ID": trace_id,
            },
        )

    return router
