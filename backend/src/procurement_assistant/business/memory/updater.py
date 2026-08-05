"""响应结束后的个人长期记忆补丁更新。"""

import asyncio
import logging

from procurement_assistant.business.domain.procurement import MemoryPatch, MemoryUpdateInput
from procurement_assistant.business.registry.model_tasks import BusinessModelTask
from procurement_assistant.core.config.settings import CoreSettings
from procurement_assistant.core.delegates.common.call_context import (
    DelegateCallContext,
    RunDeadline,
)
from procurement_assistant.core.delegates.database.interface import DatabaseDelegate
from procurement_assistant.core.delegates.model.interface import ModelDelegate
from procurement_assistant.core.domain.errors import DelegateTimeoutError, RetryableDelegateError
from procurement_assistant.core.memory.interface import MemoryUpdateRequest
from procurement_assistant.core.observability.collector import TraceCollector
from procurement_assistant.core.observability.flusher import TraceFlusher
from procurement_assistant.core.observability.models import SpanKind
from procurement_assistant.core.shared.clock import Clock
from procurement_assistant.core.shared.ids import IdGenerator


class MemoryUpdater:
    """生成 ``MemoryPatch`` 并在短事务中合并到最新个人记忆。

    读取记忆、调用模型、合并补丁是三个明确阶段。最慢的模型调用位于数据库事务之外；
    最终 ``merge_memory`` 必须由 Database Delegate 在事务中重新读取最新 JSON 后合并，
    从而避免同一用户多个 thread 同时完成时整份覆盖彼此结果。
    """

    def __init__(
        self,
        *,
        settings: CoreSettings,
        database: DatabaseDelegate,
        model: ModelDelegate,
        trace_flusher: TraceFlusher,
        clock: Clock,
        ids: IdGenerator,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._model = model
        self._trace_flusher = trace_flusher
        self._clock = clock
        self._ids = ids
        self._logger = logger or logging.getLogger(__name__)

    async def update(self, request: MemoryUpdateRequest) -> None:
        """尽力完成一次记忆更新；任何失败都不向用户响应反向传播。"""

        collector = TraceCollector(
            trace_id=request.trace_id,
            run_id=request.run_id,
            thread_id=request.thread_id,
            user_id=request.user_id,
            ids=self._ids,
            clock=self._clock,
        )
        try:
            async with collector.start_span(
                kind=SpanKind.MEMORY,
                name="memory.update",
                target="personal_memory",
                input_json={
                    "turn_input": request.turn_input,
                    "assistant_texts": request.assistant_texts,
                },
                parent_span_id=request.parent_span_id,
            ) as memory_span:
                patch = await self._build_patch(request, collector)
                if patch.updates or patch.remove_keys:
                    async with collector.start_span(
                        kind=SpanKind.DATABASE,
                        name="database.memory.merge",
                        target="personal_memory",
                        input_json=patch,
                    ) as merge_span:
                        await self._database.merge_memory(
                            request.user_id,
                            patch.updates,
                            patch.remove_keys,
                            request.run_id,
                        )
                        merge_span.set_output({"merged": True})
                memory_span.set_output(patch)
        except asyncio.CancelledError:
            # 优雅停止超时会取消任务；span 上下文会把状态标为 CANCELLED，仍尽力落库。
            raise
        except Exception:
            self._logger.exception(
                "个人记忆更新失败，run_id=%s trace_id=%s",
                request.run_id,
                request.trace_id,
            )
        finally:
            await self._trace_flusher.flush(collector)

    async def _build_patch(
        self,
        request: MemoryUpdateRequest,
        collector: TraceCollector,
    ) -> MemoryPatch:
        """读取当前记忆并调用结构化模型；单次最多 15 秒、总计最多 100 秒。"""

        async with collector.start_span(
            kind=SpanKind.DATABASE,
            name="database.memory.load",
            target="personal_memory",
        ) as load_span:
            current_memory = await self._database.load_memory(request.user_id)
            load_span.set_output(current_memory)

        model_input = MemoryUpdateInput(
            turn_input=request.turn_input,
            assistant_texts=request.assistant_texts,
            current_memory=current_memory,
        )
        deadline = RunDeadline.after(self._settings.run_deadline_seconds)
        last_error: Exception | None = None
        for attempt in range(1, self._settings.delegate_max_attempts + 1):
            deadline.ensure_remaining()
            timeout_seconds = min(
                self._settings.delegate_attempt_timeout_seconds,
                deadline.remaining_seconds,
            )
            try:
                async with collector.start_span(
                    kind=SpanKind.MODEL,
                    name="model.memory_update",
                    target=BusinessModelTask.MEMORY_UPDATE,
                    attempt=attempt,
                    input_json=model_input,
                ) as model_span:
                    if model_span.span is None:
                        raise RuntimeError("记忆模型 span 未正确启动")
                    call_context = DelegateCallContext(
                        trace_id=request.trace_id,
                        parent_span_id=model_span.span.span_id,
                        run_id=request.run_id,
                        deadline=deadline,
                        attempt=attempt,
                    )
                    try:
                        async with asyncio.timeout(timeout_seconds):
                            patch = await self._model.invoke_structured(
                                task_id=BusinessModelTask.MEMORY_UPDATE,
                                input_data=model_input,
                                output_type=MemoryPatch,
                                context=call_context,
                            )
                    except TimeoutError as exc:
                        raise DelegateTimeoutError("记忆更新模型调用超时") from exc
                    model_span.mark_final_result()
                    model_span.set_output(patch)
                    return patch
            except (DelegateTimeoutError, RetryableDelegateError) as exc:
                last_error = exc
                if attempt >= self._settings.delegate_max_attempts:
                    raise

        # 配置至少允许一次尝试，循环不可能自然落到这里；保护用于类型检查和未来改动。
        if last_error is not None:
            raise last_error
        raise RuntimeError("记忆模型没有执行任何一次尝试")
