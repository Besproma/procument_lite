"""LangGraph 官方 PostgreSQL Saver 的 OpenGauss 适配边界。"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from procurement_assistant.core.delegates.database.connection_types import OpenGaussPool


class OpenGaussCheckpointDelegate:
    """集中持有官方 Saver，业务代码永远不直接依赖其包路径。

    当前优先验证 PostgreSQL Saver 与目标 OpenGauss 的兼容性。本包装不伪造兼容层，也不
    在应用启动时偷偷运行 ``setup()`` 修改表；接入生产前必须从锁定依赖提取同版本显式
    迁移，并以 interrupt/resume、pending writes 和并发测试完成 OpenGauss 生产验证。
    """

    def __init__(self, pool: OpenGaussPool) -> None:
        self._saver = AsyncPostgresSaver(pool)

    @property
    def saver(self) -> AsyncPostgresSaver:
        """只允许 Composition Root 取得并传给 ``graph.compile``。"""

        return self._saver
