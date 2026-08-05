"""Core 管理后台记忆任务时依赖的最小接口。"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MemoryUpdateRequest:
    """一个 Run 完成后交给记忆实现的通用上下文。"""

    user_id: str
    thread_id: str
    run_id: str
    trace_id: str
    parent_span_id: str | None
    turn_input: dict[str, Any]
    assistant_texts: tuple[str, ...]


class MemoryUpdater(Protocol):
    """Business 注入的长期记忆内容更新器。"""

    async def update(self, request: MemoryUpdateRequest) -> None:
        """根据一次对话更新记忆；失败不得反向影响已经返回的响应。"""
