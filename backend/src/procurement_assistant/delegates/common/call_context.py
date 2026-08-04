"""一次 Delegate 调用所需的治理上下文。"""

from dataclasses import dataclass
from time import monotonic

from procurement_assistant.domain.errors import RunDeadlineExceededError


@dataclass(frozen=True, slots=True)
class RunDeadline:
    """使用单调时钟计算 Run 剩余时间。

    系统时间可能被 NTP 调整，不能用于超时倒计时。单调时钟只增不减，适合保证整个
    Run 不会越过配置的 100 秒总截止时间。
    """

    expires_at_monotonic: float

    @classmethod
    def after(cls, seconds: float) -> "RunDeadline":
        """从当前时刻创建一个总截止时间。"""

        return cls(expires_at_monotonic=monotonic() + seconds)

    @property
    def remaining_seconds(self) -> float:
        """返回非负剩余秒数。"""

        return max(0.0, self.expires_at_monotonic - monotonic())

    def ensure_remaining(self) -> None:
        """没有剩余时间时立即抛出稳定领域错误。"""

        if self.remaining_seconds <= 0:
            raise RunDeadlineExceededError("本次处理时间已超过系统上限，请重试")


@dataclass(frozen=True, slots=True)
class DelegateCallContext:
    """传给每个 Delegate 的最小调用上下文。

    它只包含 Trace、截止时间和当前尝试次数，不携带整个依赖容器，避免 Delegate 通过
    上下文任意访问其他能力。
    """

    trace_id: str
    parent_span_id: str
    run_id: str
    deadline: RunDeadline
    attempt: int = 1

    def for_attempt(self, attempt: int, parent_span_id: str | None = None) -> "DelegateCallContext":
        """创建下一次自动尝试的不可变上下文。"""

        return DelegateCallContext(
            trace_id=self.trace_id,
            parent_span_id=parent_span_id or self.parent_span_id,
            run_id=self.run_id,
            deadline=self.deadline,
            attempt=attempt,
        )
