"""知识全集的进程内 TTL 缓存。"""

import asyncio
from enum import StrEnum
from time import monotonic

from pydantic import BaseModel, ConfigDict

from procurement_assistant.delegates.common.call_context import DelegateCallContext
from procurement_assistant.delegates.services.knowledge import KnowledgeDelegate
from procurement_assistant.domain.errors import ProcurementAssistantError
from procurement_assistant.domain.procurement import KnowledgeResult


class KnowledgeCacheSource(StrEnum):
    """本次知识读取来自哪里。"""

    FRESH = "fresh"
    CACHED = "cached"
    STALE = "stale"


class KnowledgeCacheRead(BaseModel):
    """知识全集与缓存来源。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: KnowledgeResult
    source: KnowledgeCacheSource


class CachedKnowledgeDelegate:
    """给原始 KnowledgeDelegate 增加单航班 TTL 缓存。

    进程内锁只覆盖一次刷新等待，不持有数据库连接。TTL 过期后的第一个请求刷新，其他
    同进程请求等待同一结果，避免十分钟边界瞬间把大量请求打到低频知识接口。
    """

    def __init__(self, delegate: KnowledgeDelegate, *, ttl_seconds: float) -> None:
        self._delegate = delegate
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._cached: KnowledgeResult | None = None
        self._expires_at = 0.0

    async def get(self, context: DelegateCallContext) -> KnowledgeCacheRead:
        """返回新鲜/缓存数据；刷新失败且有旧值时返回 stale。"""

        if self._cached is not None and monotonic() < self._expires_at:
            return KnowledgeCacheRead(result=self._cached, source=KnowledgeCacheSource.CACHED)

        async with self._lock:
            # 等锁期间另一个请求可能已经完成刷新，必须再次检查，不能重复调用外部接口。
            if self._cached is not None and monotonic() < self._expires_at:
                return KnowledgeCacheRead(result=self._cached, source=KnowledgeCacheSource.CACHED)
            try:
                refreshed = await self._delegate.fetch_all(context)
            except ProcurementAssistantError:
                if self._cached is not None:
                    return KnowledgeCacheRead(
                        result=self._cached,
                        source=KnowledgeCacheSource.STALE,
                    )
                raise

            self._cached = refreshed
            self._expires_at = monotonic() + self._ttl_seconds
            return KnowledgeCacheRead(result=refreshed, source=KnowledgeCacheSource.FRESH)
