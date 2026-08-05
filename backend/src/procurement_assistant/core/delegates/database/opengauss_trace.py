"""Trace Delegate 的 OpenGauss 实现。

Trace 与业务数据库共用连接池，但它不属于 Run/Action/场景事务。具体实现单独放在本
文件，使测试和业务层仅导入轻量 ``TraceDelegate`` 协议时不需要安装 Psycopg。
"""

from psycopg.types.json import Jsonb

from procurement_assistant.core.delegates.database.connection_types import OpenGaussPool
from procurement_assistant.core.delegates.database.trace import TraceDelegate
from procurement_assistant.core.observability.collector import safe_json
from procurement_assistant.core.observability.models import TraceSpan


class OpenGaussTraceDelegate(TraceDelegate):
    """把一批完整 span 写入 ``trace_spans``。"""

    def __init__(self, *, pool: OpenGaussPool) -> None:
        self._pool = pool

    async def save_spans(self, spans: tuple[TraceSpan, ...]) -> None:
        """使用一次短事务和 ``executemany`` 保存一条调用链。

        ``span_id`` 是幂等键：请求收尾阶段如果因网络或进程调度重复刷新同一批数据，
        ``ON CONFLICT`` 会保留第一次完整记录，不会生成重复耗时样本。
        """

        if not spans:
            return
        values = [
            (
                span.span_id,
                span.trace_id,
                span.parent_span_id,
                span.run_id,
                span.thread_id,
                span.user_id,
                span.kind.value,
                span.name,
                span.target,
                span.attempt,
                span.status.value,
                span.started_at,
                span.finished_at,
                span.duration_ms,
                span.first_byte_ms,
                span.first_text_delta_ms,
                span.final_result_ms,
                Jsonb(safe_json(span.input_json)),
                Jsonb(safe_json(span.output_json)),
                span.error_code,
                Jsonb(safe_json(span.attributes)),
            )
            for span in spans
        ]
        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        """
                        INSERT INTO trace_spans (
                            span_id, trace_id, parent_span_id, run_id, thread_id,
                            user_id, span_kind, name, target, attempt, status,
                            started_at, finished_at, duration_ms, first_byte_ms,
                            first_text_delta_ms, final_result_ms, input_json,
                            output_json, error_code, attributes_json
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (span_id) DO NOTHING
                        """,
                        values,
                    )
