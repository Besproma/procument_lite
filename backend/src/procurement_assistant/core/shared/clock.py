"""统一时钟，避免业务代码直接散落 ``datetime.now``。"""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """可在测试中替换的 UTC 时钟接口。"""

    def now(self) -> datetime:
        """返回带时区的当前 UTC 时间。"""


class SystemClock:
    """生产环境使用的系统 UTC 时钟。"""

    def now(self) -> datetime:
        """返回带 UTC 时区的当前时间。"""

        return datetime.now(UTC)
