"""FastAPI 所需对象的显式运行时容器。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from procurement_assistant.core.api.capacity import RunCapacityLimiter
from procurement_assistant.core.config.settings import CoreSettings
from procurement_assistant.core.delegates.database.interface import DatabaseDelegate
from procurement_assistant.core.memory.interface import MemoryUpdater
from procurement_assistant.core.memory.task_manager import ManagedTaskSet
from procurement_assistant.core.observability.flusher import TraceFlusher
from procurement_assistant.core.orchestration.application import AgentApplication
from procurement_assistant.core.protocol.snapshot import SnapshotBlockPolicy
from procurement_assistant.core.shared.clock import Clock
from procurement_assistant.core.shared.ids import IdGenerator

ReadinessProbe = Callable[[], Awaitable[tuple[bool, str]]]
CloseResources = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class APIRuntime:
    """Composition Root 创建后交给 API 的最小对象集合。"""

    settings: CoreSettings
    application: AgentApplication
    database: DatabaseDelegate
    snapshot_policy: SnapshotBlockPolicy
    trace_flusher: TraceFlusher
    memory_updater: MemoryUpdater
    background_tasks: ManagedTaskSet
    capacity: RunCapacityLimiter
    clock: Clock
    ids: IdGenerator
    readiness_probe: ReadinessProbe
    start_resources: CloseResources
    close_resources: CloseResources
