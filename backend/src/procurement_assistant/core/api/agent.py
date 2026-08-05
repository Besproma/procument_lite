"""采购助手主接口：接收一次用户操作，并把处理结果持续推送给前端。

初次阅读本项目时，可以把本文件理解成“前台接待员”：

1. 接收并检查请求；
2. 登记本次处理，防止重复提交；
3. 把请求交给应用层和 LangGraph；
4. 一边处理，一边通过 SSE 把文字、表单、按钮等事件返回给浏览器；
5. 无论成功、失败还是浏览器断开，都释放容量并保存耗时记录。

这里负责 HTTP 和流式返回，不在这里编写 IOI、栏目、自采等具体采购判断。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from procurement_assistant.core.api.dependencies import get_user_id
from procurement_assistant.core.api.errors import error_response
from procurement_assistant.core.api.runtime import APIRuntime
from procurement_assistant.core.api.sse import encode_sse_event
from procurement_assistant.core.delegates.common.call_context import RunDeadline
from procurement_assistant.core.domain.errors import (
    ProcurementAssistantError,
    ServiceOverloadedError,
)
from procurement_assistant.core.memory.interface import MemoryUpdateRequest
from procurement_assistant.core.observability.collector import TraceCollector
from procurement_assistant.core.observability.models import SpanKind
from procurement_assistant.core.orchestration.runtime import ExecutionContext
from procurement_assistant.core.protocol.emitter import AGUIEventEmitter
from procurement_assistant.core.protocol.events import TextMessageContentEvent
from procurement_assistant.core.protocol.run_input import RunAgentInput

# 队列中既要放正常的 Pydantic 事件，也需要一个“已经没有更多事件”的标记。
# 单独创建 object 可以保证它不会与任何正常事件相等；消费者读到它就结束 SSE 流。
_END_OF_STREAM = object()
_LOGGER = logging.getLogger(__name__)


class _SafeInternalError(ProcurementAssistantError):
    """只在入口尚未打开 SSE 时使用的固定内部错误。"""

    code = "INTERNAL_ERROR"


def build_agent_router(runtime: APIRuntime) -> APIRouter:
    """创建并返回 Agent Router。

    这是一个“Router 工厂函数”：应用启动时调用一次。内部的 ``run_agent`` 会记住
    ``runtime``，以后每次请求都使用同一套已经装配好的应用服务、数据库、计时器等对象。
    具体采购业务仍位于 Application 和 Graph 中。
    """

    router = APIRouter(prefix="/api/v1", tags=["agent"])

    @router.post("/agent")
    async def run_agent(
        http_request: Request,
        run_input: RunAgentInput,
        user_id: Annotated[str, Depends(get_user_id)],
    ) -> Response:
        """处理一次 ``POST /api/v1/agent`` 请求。

        FastAPI 在调用本函数前已经完成三件事：

        - 把 HTTP JSON 转换并校验成 ``RunAgentInput``；
        - 通过 ``get_user_id`` 读取并校验 ``X-User-ID`` 请求头；
        - 运行 ``app.py`` 中的中间件，为请求生成 ``trace_id``。

        因此能进入函数体，说明请求的基本结构已经合法。
        """

        # trace_id 是“整条调用链的查询编号”。以后查某次请求为什么慢或为什么失败，
        # 就用它查出 HTTP、数据库、模型、外围 Agent 和 Graph 的全部耗时记录。
        trace_id = http_request.state.trace_id

        # collector 可以理解为本次请求专用的“计时记录本”。
        # 每执行一个重要步骤，就往里面添加一条 span（单步骤计时记录）。
        collector = TraceCollector(
            trace_id=trace_id,
            run_id=run_input.run_id,
            thread_id=run_input.thread_id,
            user_id=user_id,
            ids=runtime.ids,
            clock=runtime.clock,
        )

        # root_span 是本次 HTTP 请求的“总计时器”，也是所有子计时器的根节点：
        #
        # root_span（整个 POST /api/v1/agent）
        # ├── 数据库登记耗时
        # ├── ReAct / LangGraph 耗时
        # ├── 模型或外围 Agent 耗时
        # └── 数据库保存结果耗时
        #
        # 它不只是记录 run_agent 函数返回的时间，而是一直记录到 SSE 最后一条数据发送
        # 完成或浏览器断开。这样查询到的“总耗时”才与用户实际等待时间接近。
        root_span = collector.start_span(
            kind=SpanKind.HTTP,
            name="http.post_agent",
            target="POST /api/v1/agent",
            input_json=run_input,
            # 更深入的实现原因：root_span 会跨越路由函数和 StreamingResponse 生成器，
            # 两段代码可能运行在不同异步任务中，所以不让它自动修改 ContextVar；需要
            # 建立子计时器时，再使用 parent_scope(root_span_id) 明确指定父节点。
            bind_as_parent=False,
        )

        # 通常计时器写成 ``async with ...``。这里必须手动开始，因为本函数返回
        # StreamingResponse 时响应正文还没有发送完；root_span 要到流结束时才能关闭。
        await root_span.__aenter__()
        if root_span.span is None:
            raise RuntimeError("HTTP 根 span 未正确启动")

        # root_span 是计时器对象，root_span.span 才是已经创建的那条数据记录。
        # 取出 span_id 后，后续小步骤就能声明“我的父记录是这次 HTTP 请求”。
        root_span_id = root_span.span.span_id

        # 先占用一个“正在处理的请求名额”。达到系统配置的并发上限时立即返回繁忙，
        # 不再继续访问数据库或外围 Agent，避免过载后所有请求一起变慢。
        capacity_acquired = await runtime.capacity.try_acquire()
        if not capacity_acquired:
            error = ServiceOverloadedError("系统当前请求较多，请稍后重试")
            await root_span.__aexit__(type(error), error, None)
            await runtime.trace_flusher.flush(collector)
            return error_response(error, trace_id=trace_id)

        try:
            # admission 可以理解为“正式受理前登记”：
            # 1. 检查同一个 runId 是否已经处理过，防止网络重试造成重复操作；
            # 2. 锁定当前 thread，保证同一会话一次只处理一个请求；
            # 3. 如果用户点了按钮或提交表单，原子消费对应的一次性 Action。
            #
            # 这是 SSE 打开前的短数据库事务。只有登记成功后才返回 HTTP 200；如果登记
            # 失败，仍然可以使用普通 HTTP 状态码（400、409、503 等）清楚地告诉前端。
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
            # 此时还没有开始 SSE，可以直接返回结构化 HTTP 错误。
            await runtime.capacity.release()
            await root_span.__aexit__(type(error), error, None)
            await runtime.trace_flusher.flush(collector)
            return error_response(
                error,
                trace_id=trace_id,
                thread_id=run_input.thread_id,
            )
        except Exception as error:
            # 未预料到的错误只记录到服务端日志，不把堆栈、SQL 等内部信息发给用户。
            await runtime.capacity.release()
            await root_span.__aexit__(type(error), error, None)
            await runtime.trace_flusher.flush(collector)
            _LOGGER.exception("Run 入口登记发生未知异常，trace_id=%s", trace_id)
            return error_response(
                _SafeInternalError("系统暂时无法处理，请稍后重试"),
                trace_id=trace_id,
            )

        # queue 是本次请求内部的一条“事件传送带”：
        # Graph/应用层是生产者，把文字、表单、商品等事件放进来；
        # stream_events 是消费者，按放入顺序取出并发送给浏览器。
        # 每个请求都有自己的 queue，不同用户的数据不会混在一起。
        queue: asyncio.Queue[BaseModel | object] = asyncio.Queue()

        async def event_sink(event: BaseModel) -> None:
            """接收一个业务事件，并把它放到本次请求的传送带上。

            Graph 节点只负责“产生什么事件”，不直接操作浏览器连接。这样业务代码不需要
            理解 ASGI/SSE，也不会因为前端网络速度影响节点的职责边界。
            """

            await queue.put(event)

        # emitter 是统一的“事件包装器”。业务层调用 text_message/custom 等方法时，
        # 它负责补充 threadId、runId、事件序号并把事件交给上面的 event_sink。
        emitter = AGUIEventEmitter(
            thread_id=run_input.thread_id,
            run_id=run_input.run_id,
            sink=event_sink,
        )

        # execution_context 是本次 Run 随身携带的“工具包”。Graph 的每个节点都可以从中
        # 取得用户/会话编号、页面区域、总截止时间、事件发射器和 Trace 收集器；它不是
        # 采购业务状态，不会作为 LangGraph Checkpoint 保存。
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
            settings=runtime.settings,
        )

        # 业务执行和 SSE 发送在两个异步任务中运行，不能像普通函数那样直接接住返回值和
        # 异常。这里用两个请求内的小列表充当“结果盒子”和“错误盒子”，供流结束时收尾。
        result_holder: list[Any] = []
        execution_errors: list[BaseException] = []

        async def execute_application() -> None:
            """生产者任务：运行应用层和 Graph，不断产生事件。

            它与 ``stream_events`` 同时运行，因此 Graph 不必全部完成后才返回结果；节点
            每产生一条事件，浏览器都可以尽快看到。
            """

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
                # 浏览器断开时生产者会被取消。保留错误，最终把 root_span 标记为取消。
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
                # 无论成功、失败还是取消，都放入“结束牌”。否则消费者会永远等待下一条
                # queue.get()，HTTP 连接也就无法正常结束。
                await queue.put(_END_OF_STREAM)

        async def stream_events() -> AsyncIterator[bytes]:
            """消费者任务：从队列取事件，编码成 SSE 后逐条交给浏览器。

            这是异步生成器。普通函数使用 ``return`` 一次返回一个结果；生成器使用
            ``yield`` 多次返回数据，所以浏览器可以边接收、边更新页面。
            """

            # create_task 让业务生产者开始运行；当前生成器则继续负责消费事件。两者在
            # 遇到 await 时互相让出执行权，并不是为每个请求额外创建操作系统线程。
            producer = asyncio.create_task(
                execute_application(),
                name=f"agent-run-{run_input.run_id}",
            )
            stream_error: BaseException | None = None
            try:
                while True:
                    # 队列暂时为空时，await 会让出执行权，等待生产者放入下一条事件。
                    event = await queue.get()
                    if event is _END_OF_STREAM:
                        break
                    if not isinstance(event, BaseModel):
                        raise RuntimeError("SSE 队列包含未校验事件")
                    root_span.mark_first_byte()
                    if isinstance(event, TextMessageContentEvent):
                        root_span.mark_first_text_delta()
                    # encode_sse_event 把 Pydantic 事件变成 ``data: {...}\n\n``；yield 将
                    # 这一帧立即交给 FastAPI/ASGI，再由网络发送给前端。
                    yield encode_sse_event(event)

                # 读到结束牌后确认生产者确实完成；如果生产者被取消，这里会获知结果。
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
                    # 生成器只有在上一帧交给 ASGI 后才会继续，因此此时 RUN_FINISHED 已经
                    # 交付网络层。长期记忆更新不是本次回答的必要步骤，放到后台运行，避免
                    # 用户为了非关键个性化记忆继续等待。
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
                # finally 是统一收尾区：正常结束、代码报错、浏览器中断都会执行。
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
                final_error = stream_error or (execution_errors[0] if execution_errors else None)

                # 直到这里才关闭总计时器，所以 root_span.duration_ms 包含实际流式处理时间。
                await root_span.__aexit__(
                    type(final_error) if final_error is not None else None,
                    final_error,
                    None,
                )
                # 归还开头占用的并发名额，并把本次收集到的所有 span 批量写入数据库。
                await runtime.capacity.release()
                await runtime.trace_flusher.flush(collector)

        # 返回 StreamingResponse 只是把“如何持续产生正文”交给 FastAPI；此时业务不一定
        # 已经完成。FastAPI 随后迭代 stream_events()，每得到一个 yield 就发送一帧 SSE。
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
