"""场景、Run 和 Action 的生命周期枚举。"""

from enum import StrEnum


class ScenarioStatus(StrEnum):
    """一个跨 Turn 场景实例的状态。"""

    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    ABORTED = "aborted"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        """终态不能再通过旧 Action 恢复。"""

        return self in {self.COMPLETED, self.ABORTED, self.EXPIRED}


class RunStatus(StrEnum):
    """一次 HTTP Run 的持久化状态。"""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class ActionStatus(StrEnum):
    """一次性用户操作的持久化状态。"""

    PENDING = "pending"
    CONSUMED = "consumed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class InputSource(StrEnum):
    """场景由按钮还是自然语言触发。"""

    BUTTON = "button"
    NATURAL_LANGUAGE = "natural_language"
