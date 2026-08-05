"""不依赖具体数据库驱动的 Trace 落库边界。"""

from typing import Protocol

from procurement_assistant.core.observability.models import TraceSpan


class TraceDelegate(Protocol):
    """批量把一个 Run 的 span 写入 OpenGauss。"""

    async def save_spans(self, spans: tuple[TraceSpan, ...]) -> None:
        """短事务批量写入；失败不能反向改变已经完成的业务 Run。"""
