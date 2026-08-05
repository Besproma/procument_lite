"""把请求局部 Trace 安全批量写入持久化 Delegate。"""

import logging
from time import monotonic

from procurement_assistant.core.delegates.database.trace import TraceDelegate
from procurement_assistant.core.observability.collector import TraceCollector
from procurement_assistant.core.observability.models import SpanKind, SpanStatus, TraceSpan
from procurement_assistant.core.shared.clock import Clock
from procurement_assistant.core.shared.ids import IdGenerator


class TraceFlusher:
    """负责 Trace 的“尽力而为”落库语义。

    业务执行和 Trace 保存必须单向依赖：即使 Trace 数据库短暂失败，已经成功的采购业务
    也不能被改写成失败。失败会写服务日志，运维可以据此排查监控数据缺口。
    """

    def __init__(
        self,
        *,
        delegate: TraceDelegate,
        clock: Clock,
        ids: IdGenerator,
        logger: logging.Logger | None = None,
    ) -> None:
        self._delegate = delegate
        self._clock = clock
        self._ids = ids
        self._logger = logger or logging.getLogger(__name__)

    async def flush(self, collector: TraceCollector) -> bool:
        """保存当前收集器的全部 span，并单独记录一次 flush 耗时。

        ``trace.flush`` 不放进第一批数据，因为必须等第一批写完才知道实际耗时。它在
        第二个短事务中单独保存；第二次写入本身不再递归创建新 span。
        """

        spans = tuple(span.model_copy(deep=True) for span in collector.spans)
        if not spans:
            return True

        started_at = self._clock.now()
        started_monotonic = monotonic()
        try:
            await self._delegate.save_spans(spans)
        except Exception:
            # 日志只记录 trace_id，不打印可能带完整业务输入的 span，也不暴露 Delegate
            # 内部连接信息。具体堆栈由 logger.exception 写到受控服务日志。
            self._logger.exception("Trace 批量落库失败，trace_id=%s", collector.trace_id)
            return False

        finished_at = self._clock.now()
        # 记忆更新使用与 HTTP Run 相同 trace_id，但在响应后由独立收集器保存；它的首个
        # span 已经指向 HTTP 根 span，因此本批次未必存在 parent=None 的真正根节点。
        root_span = next((span for span in spans if span.parent_span_id is None), spans[0])
        flush_span = TraceSpan(
            trace_id=collector.trace_id,
            span_id=self._ids.new("span"),
            parent_span_id=root_span.span_id if root_span is not None else None,
            run_id=collector.run_id,
            thread_id=collector.thread_id,
            user_id=collector.user_id,
            kind=SpanKind.DATABASE,
            name="trace.flush",
            target="trace_store",
            status=SpanStatus.OK,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=(monotonic() - started_monotonic) * 1000,
            attributes={"saved_span_count": len(spans)},
        )
        try:
            await self._delegate.save_spans((flush_span,))
        except Exception:
            self._logger.exception(
                "Trace flush 自身耗时记录失败，trace_id=%s",
                collector.trace_id,
            )
        return True
