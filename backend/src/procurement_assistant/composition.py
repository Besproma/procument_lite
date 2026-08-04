"""采购助手唯一的生产依赖装配入口。"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI

from procurement_assistant.api.app import create_app
from procurement_assistant.api.capacity import RunCapacityLimiter
from procurement_assistant.api.runtime import APIRuntime
from procurement_assistant.config import AppEnvironment, AppSettings
from procurement_assistant.delegates.agents.column_recognition import (
    ColumnRecognitionDelegate,
)
from procurement_assistant.delegates.agents.duplicate_self_purchase import (
    DuplicateSelfPurchaseDelegate,
)
from procurement_assistant.delegates.agents.ioi import IOIProcurementDelegate
from procurement_assistant.delegates.database.interface import DatabaseDelegate
from procurement_assistant.delegates.database.trace import TraceDelegate
from procurement_assistant.delegates.model.interface import ModelDelegate
from procurement_assistant.delegates.services.cached_knowledge import CachedKnowledgeDelegate
from procurement_assistant.delegates.services.knowledge import KnowledgeDelegate
from procurement_assistant.delegates.services.product_search import ProductSearchDelegate
from procurement_assistant.delegates.services.queue import QueueDelegate
from procurement_assistant.domain.errors import ConfigurationError
from procurement_assistant.memory.task_manager import ManagedTaskSet
from procurement_assistant.memory.updater import MemoryUpdater
from procurement_assistant.observability.checkpointer import TracingCheckpointSaver
from procurement_assistant.observability.flusher import TraceFlusher
from procurement_assistant.orchestration.application import AgentApplication
from procurement_assistant.orchestration.catalog.catalog import build_scenario_catalog
from procurement_assistant.orchestration.graph_runner import GraphRunner
from procurement_assistant.orchestration.router.react_router import ReactScenarioRouter
from procurement_assistant.orchestration.router.scene_switch import SceneSwitchCoordinator
from procurement_assistant.orchestration.scenarios.knowledge.graph import build_knowledge_graph
from procurement_assistant.orchestration.scenarios.knowledge.nodes import KnowledgeNodes
from procurement_assistant.orchestration.scenarios.smart_routing.graph import (
    build_smart_routing_graph,
)
from procurement_assistant.orchestration.scenarios.smart_routing.nodes import (
    SmartRoutingNodes,
)
from procurement_assistant.orchestration.subgraphs.product_recommendation.graph import (
    build_product_recommendation_graph,
)
from procurement_assistant.orchestration.subgraphs.product_recommendation.nodes import (
    ProductRecommendationNodes,
)
from procurement_assistant.orchestration.wait_factory import WaitRequestFactory
from procurement_assistant.prompts.catalog import load_all_prompts
from procurement_assistant.shared.clock import Clock, SystemClock
from procurement_assistant.shared.ids import IdGenerator, UuidIdGenerator

LifecycleCallback = Callable[[], Awaitable[None]]
ReadinessProbe = Callable[[], Awaitable[tuple[bool, str]]]


async def _no_op() -> None:
    """默认生命周期回调。"""


async def _ready() -> tuple[bool, str]:
    """调用方没有额外依赖检查时的安全默认值。"""

    return True, "ready"


def build_runtime(
    *,
    settings: AppSettings,
    database: DatabaseDelegate,
    trace_delegate: TraceDelegate,
    checkpointer: Any,
    model: ModelDelegate,
    ioi: IOIProcurementDelegate,
    columns: ColumnRecognitionDelegate,
    duplicate_self_purchase: DuplicateSelfPurchaseDelegate,
    product_search: ProductSearchDelegate,
    knowledge: KnowledgeDelegate,
    queue: QueueDelegate,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    readiness_probe: ReadinessProbe = _ready,
    start_resources: LifecycleCallback = _no_op,
    close_resources: LifecycleCallback = _no_op,
) -> APIRuntime:
    """按固定顺序创建 Graph、应用服务和 API 运行时。

    本函数只接受明确对象，不读取环境变量、不扫描目录，也不根据字符串动态 import。
    测试装配可以从 ``test_support`` 传入 Fake，但本生产模块永远不会反向 import Fake。
    """

    load_all_prompts()
    resolved_clock = clock or SystemClock()
    resolved_ids = ids or UuidIdGenerator()
    catalog = build_scenario_catalog()
    waits = WaitRequestFactory(
        clock=resolved_clock,
        ids=resolved_ids,
        ttl_hours=settings.checkpoint_ttl_hours,
    )

    product_nodes = ProductRecommendationNodes(
        model=model,
        search=product_search,
        settings=settings,
    )
    product_graph = build_product_recommendation_graph(product_nodes)

    cached_knowledge = CachedKnowledgeDelegate(
        knowledge,
        ttl_seconds=settings.knowledge_cache_ttl_seconds,
    )
    smart_nodes = SmartRoutingNodes(
        settings=settings,
        model=model,
        ioi=ioi,
        columns=columns,
        duplicate_self_purchase=duplicate_self_purchase,
        queue=queue,
        product_graph=product_graph,
        waits=waits,
    )
    knowledge_nodes = KnowledgeNodes(
        settings=settings,
        knowledge=cached_knowledge,
        waits=waits,
    )
    traced_checkpointer = TracingCheckpointSaver(checkpointer)
    graphs = {
        "smart_routing": build_smart_routing_graph(
            smart_nodes,
            checkpointer=traced_checkpointer,
        ),
        "knowledge_recommendation": build_knowledge_graph(
            knowledge_nodes,
            checkpointer=traced_checkpointer,
        ),
    }

    runner = GraphRunner(
        database=database,
        catalog=catalog,
        graphs=graphs,
        clock=resolved_clock,
        ids=resolved_ids,
        checkpoint_ttl_hours=settings.checkpoint_ttl_hours,
        waits=waits,
    )
    router = ReactScenarioRouter(
        model=model,
        catalog=catalog,
        settings=settings,
    )
    scene_switch = SceneSwitchCoordinator(
        database=database,
        router=router,
        runner=runner,
        waits=waits,
    )
    application = AgentApplication(
        settings=settings,
        database=database,
        router=router,
        runner=runner,
        scene_switch=scene_switch,
        clock=resolved_clock,
        ids=resolved_ids,
    )
    trace_flusher = TraceFlusher(
        delegate=trace_delegate,
        clock=resolved_clock,
        ids=resolved_ids,
    )
    memory_updater = MemoryUpdater(
        settings=settings,
        database=database,
        model=model,
        trace_flusher=trace_flusher,
        clock=resolved_clock,
        ids=resolved_ids,
    )
    return APIRuntime(
        settings=settings,
        application=application,
        database=database,
        trace_flusher=trace_flusher,
        memory_updater=memory_updater,
        background_tasks=ManagedTaskSet(),
        capacity=RunCapacityLimiter(settings.max_concurrent_runs),
        clock=resolved_clock,
        ids=resolved_ids,
        readiness_probe=readiness_probe,
        start_resources=start_resources,
        close_resources=close_resources,
    )


def build_production_app(settings: AppSettings | None = None) -> FastAPI:
    """装配真实模型与 OpenGauss；绝不回退到 Fake。

    外围业务协议尚未提供，因此生产装配使用明确 ``NotConfigured`` Delegate，并在 ready
    检查中返回未就绪。收到正式协议后逐个替换对应对象，不修改 Graph 或 API。
    """

    resolved_settings = settings or AppSettings()
    if resolved_settings.app_env != AppEnvironment.PRODUCTION:
        raise ConfigurationError("生产入口要求 APP_ENV=production；本地 Fake 请使用 test_support")

    # 这些 import 有意留在生产工厂内部：本地集成测试不会因为未安装 Psycopg 或
    # langgraph-checkpoint-postgres 而误创建生产连接，生产启动则会立即发现依赖缺失。
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from procurement_assistant.delegates.agents.column_recognition import (
        NotConfiguredColumnRecognitionDelegate,
    )
    from procurement_assistant.delegates.agents.duplicate_self_purchase import (
        NotConfiguredDuplicateSelfPurchaseDelegate,
    )
    from procurement_assistant.delegates.agents.ioi import (
        NotConfiguredIOIProcurementDelegate,
    )
    from procurement_assistant.delegates.common.http_client import SharedHttpClient
    from procurement_assistant.delegates.database.checkpoints import (
        OpenGaussCheckpointDelegate,
    )
    from procurement_assistant.delegates.database.connection_types import (
        OpenGaussConnection,
    )
    from procurement_assistant.delegates.database.opengauss import OpenGaussDatabaseDelegate
    from procurement_assistant.delegates.database.opengauss_trace import (
        OpenGaussTraceDelegate,
    )
    from procurement_assistant.delegates.model.openai_compatible import (
        OpenAICompatibleModelDelegate,
    )
    from procurement_assistant.delegates.services.knowledge import (
        NotConfiguredKnowledgeDelegate,
    )
    from procurement_assistant.delegates.services.product_search import (
        NotConfiguredProductSearchDelegate,
    )
    from procurement_assistant.delegates.services.queue import NotConfiguredQueueDelegate

    if resolved_settings.database_dsn is None:
        raise ConfigurationError("production 缺少 DATABASE_DSN")
    dsn = resolved_settings.database_dsn.get_secret_value()
    # 所有正式外围 Delegate 共用一个连接池客户端。当前协议尚未提供，NotConfigured
    # 实现不会发请求；仍在 Composition Root 建立并纳入生命周期，收到协议后只替换
    # Delegate 装配，不需要改 API 或 Graph 的资源管理边界。
    http_client = SharedHttpClient(
        max_connections=resolved_settings.http_max_connections,
        max_keepalive_connections=resolved_settings.http_max_keepalive_connections,
        max_response_bytes=resolved_settings.http_max_response_bytes,
        transport_timeout_seconds=resolved_settings.delegate_attempt_timeout_seconds,
    )
    # 官方 AsyncPostgresSaver 的类型和读取逻辑都要求字典行。显式给连接池设置 row_factory
    # 后，Checkpoint、业务 SQL 和 Trace 共用同一个池时拥有一致的行类型，不需要在适配
    # 层用 cast 掩盖实际配置差异。各业务 cursor 仍可显式声明 dict_row，职责更直观。
    pool = AsyncConnectionPool[OpenGaussConnection](
        conninfo=dsn,
        kwargs={"row_factory": dict_row},
        min_size=resolved_settings.db_pool_min_size,
        max_size=resolved_settings.db_pool_max_size,
        open=False,
    )
    database = OpenGaussDatabaseDelegate(pool=pool, clock=SystemClock())
    trace_delegate = OpenGaussTraceDelegate(pool=pool)
    checkpoint_delegate = OpenGaussCheckpointDelegate(pool)

    async def start_resources() -> None:
        await pool.open()
        await pool.wait()

    async def close_resources() -> None:
        await http_client.close()
        await pool.close()

    async def readiness_probe() -> tuple[bool, str]:
        if not await database.is_ready():
            return False, "database_unavailable_or_schema_missing"
        # 外围协议仍是明确阻塞项，不能因数据库连通就误报生产 ready。
        return False, "external_delegate_protocols_not_configured"

    runtime = build_runtime(
        settings=resolved_settings,
        database=database,
        trace_delegate=trace_delegate,
        checkpointer=checkpoint_delegate.saver,
        model=OpenAICompatibleModelDelegate(resolved_settings),
        ioi=NotConfiguredIOIProcurementDelegate(),
        columns=NotConfiguredColumnRecognitionDelegate(),
        duplicate_self_purchase=NotConfiguredDuplicateSelfPurchaseDelegate(),
        product_search=NotConfiguredProductSearchDelegate(),
        knowledge=NotConfiguredKnowledgeDelegate(),
        queue=NotConfiguredQueueDelegate(),
        readiness_probe=readiness_probe,
        start_resources=start_resources,
        close_resources=close_resources,
    )
    return create_app(runtime)
