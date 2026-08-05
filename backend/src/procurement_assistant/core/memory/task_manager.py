"""进程内受管理后台任务集合。"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


class ManagedTaskSet:
    """跟踪响应后仍在运行的短任务，并在应用停止时有限等待。

    首版不引入持久任务队列，所以进程突然退出可能丢失尚未完成的记忆更新；这是已确认
    的精简架构边界。显式保存 Task 引用可以避免任务被垃圾回收，并让优雅停止有机会
    等待或取消它们。
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self, coroutine: Coroutine[Any, Any, Any], *, name: str) -> None:
        """启动并登记一个后台协程。"""

        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        """移除完成任务并读取异常，避免出现“异常从未获取”警告。"""

        self._tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._logger.error(
                "受管理后台任务异常结束：%s",
                task.get_name(),
                exc_info=(type(exception), exception, exception.__traceback__),
            )

    async def close(self, *, timeout_seconds: float) -> None:
        """停止服务时有限等待，超时后取消剩余任务。"""

        if not self._tasks:
            return
        tasks = tuple(self._tasks)
        try:
            async with asyncio.timeout(timeout_seconds):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
