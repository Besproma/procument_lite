"""单进程 Run 并发保护。"""

import asyncio


class RunCapacityLimiter:
    """使用很短的内存临界区快速接受或拒绝 Run。

    该计数器不是会话状态，也不影响横向扩展；每个进程只保护自己的事件循环、HTTP
    连接和下游连接池不被无限协程压垮。达到上限时直接拒绝，不在内存中排队等待。
    """

    def __init__(self, maximum: int) -> None:
        if maximum < 1:
            raise ValueError("Run 并发上限必须大于零")
        self._maximum = maximum
        self._active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        """有空位时占用一个名额，否则立即返回 ``False``。"""

        async with self._lock:
            if self._active >= self._maximum:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        """释放一个名额；重复释放属于开发错误。"""

        async with self._lock:
            if self._active <= 0:
                raise RuntimeError("Run 并发名额被重复释放")
            self._active -= 1

    @property
    def active(self) -> int:
        """仅供健康检查和测试读取当前进程计数。"""

        return self._active
