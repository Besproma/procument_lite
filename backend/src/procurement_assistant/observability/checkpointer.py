"""给 LangGraph Checkpointer 增加请求局部耗时记录。"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from procurement_assistant.observability.collector import current_trace_collector
from procurement_assistant.observability.models import SpanKind


class TracingCheckpointSaver(BaseCheckpointSaver[Any]):
    """透明转发官方 Saver，并记录异步读取、写入和 pending writes。

    Graph 只看到 LangGraph 标准 ``BaseCheckpointSaver``，不会依赖 OpenGauss。当前 Trace
    收集器通过 ContextVar 取得，不把 Trace 对象塞进 Graph State 或 Checkpoint。没有请求
    上下文的迁移/管理操作直接转发，避免创建没有 run_id 的伪 span。
    """

    def __init__(self, delegate: BaseCheckpointSaver[Any]) -> None:
        super().__init__(serde=getattr(delegate, "serde", None))
        self._delegate = delegate

    @property
    def config_specs(self) -> Any:
        """保持底层 Saver 的可配置字段声明。"""

        return self._delegate.config_specs

    def get_tuple(self, config: Any) -> Any:
        """同步调用只转发；当前服务所有 Graph 均使用异步 API。"""

        return self._delegate.get_tuple(config)

    def list(
        self,
        config: Any,
        *,
        filter: dict[str, Any] | None = None,
        before: Any = None,
        limit: int | None = None,
    ) -> Iterator[Any]:
        return self._delegate.list(config, filter=filter, before=before, limit=limit)

    def put(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        return self._delegate.put(config, checkpoint, metadata, new_versions)

    def put_writes(
        self,
        config: Any,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._delegate.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        self._delegate.delete_thread(thread_id)

    def get_next_version(self, current: Any, channel: Any) -> Any:
        """版本生成必须完全沿用官方 Saver，包装层不改变 Checkpoint 语义。"""

        return self._delegate.get_next_version(current, channel)

    async def aget_tuple(self, config: Any) -> Any:
        collector = current_trace_collector()
        if collector is None:
            return await self._delegate.aget_tuple(config)
        async with collector.start_span(
            kind=SpanKind.DATABASE,
            name="checkpoint.get",
            target="langgraph_checkpoint",
            input_json=config,
        ) as span:
            result = await self._delegate.aget_tuple(config)
            span.set_output({"found": result is not None})
            return result

    async def alist(
        self,
        config: Any,
        *,
        filter: dict[str, Any] | None = None,
        before: Any = None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        collector = current_trace_collector()
        if collector is None:
            async for item in self._delegate.alist(
                config,
                filter=filter,
                before=before,
                limit=limit,
            ):
                yield item
            return
        async with collector.start_span(
            kind=SpanKind.DATABASE,
            name="checkpoint.list",
            target="langgraph_checkpoint",
            input_json={"config": config, "filter": filter, "before": before, "limit": limit},
        ) as span:
            count = 0
            async for item in self._delegate.alist(
                config,
                filter=filter,
                before=before,
                limit=limit,
            ):
                count += 1
                yield item
            span.set_output({"count": count})

    async def aput(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        collector = current_trace_collector()
        if collector is None:
            return await self._delegate.aput(config, checkpoint, metadata, new_versions)
        async with collector.start_span(
            kind=SpanKind.DATABASE,
            name="checkpoint.put",
            target="langgraph_checkpoint",
            input_json={"config": config, "metadata": metadata},
        ) as span:
            result = await self._delegate.aput(config, checkpoint, metadata, new_versions)
            span.set_output(result)
            return result

    async def aput_writes(
        self,
        config: Any,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        collector = current_trace_collector()
        if collector is None:
            await self._delegate.aput_writes(config, writes, task_id, task_path)
            return
        async with collector.start_span(
            kind=SpanKind.DATABASE,
            name="checkpoint.put_writes",
            target="langgraph_checkpoint",
            input_json={"config": config, "task_id": task_id, "task_path": task_path},
        ) as span:
            await self._delegate.aput_writes(config, writes, task_id, task_path)
            span.set_output({"saved": True})

    async def adelete_thread(self, thread_id: str) -> None:
        """转发管理操作；业务请求当前不会删除 Checkpoint。"""

        await self._delegate.adelete_thread(thread_id)
