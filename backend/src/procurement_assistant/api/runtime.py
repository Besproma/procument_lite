"""FastAPI 所需对象的显式运行时容器。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from procurement_assistant.api.capacity import RunCapacityLimiter
from procurement_assistant.config import AppSettings
from procurement_assistant.delegates.database.interface import DatabaseDelegate
from procurement_assistant.memory.task_manager import ManagedTaskSet
from procurement_assistant.memory.updater import MemoryUpdater
from procurement_assistant.observability.flusher import TraceFlusher
from procurement_assistant.orchestration.application import AgentApplication
from procurement_assistant.shared.clock import Clock
from procurement_assistant.shared.ids import IdGenerator

ReadinessProbe = Callable[[], Awaitable[tuple[bool, str]]]
CloseResources = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class APIRuntime:
    """Composition Root 创建后交给 API 的最小对象集合。"""

    settings: AppSettings
    application: AgentApplication
    database: DatabaseDelegate
    trace_flusher: TraceFlusher
    memory_updater: MemoryUpdater
    background_tasks: ManagedTaskSet
    capacity: RunCapacityLimiter
    clock: Clock
    ids: IdGenerator
    readiness_probe: ReadinessProbe
    start_resources: CloseResources
    close_resources: CloseResources
