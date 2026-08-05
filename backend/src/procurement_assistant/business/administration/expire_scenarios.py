"""部署前统一结束活动场景的命令。

该命令故意不导入完整 FastAPI Composition Root：发布时外围模型和业务 Agent 可能还在
切换，过期旧 Checkpoint 只需要数据库 Delegate。这样运维操作不会意外启动 HTTP 服务、
创建模型客户端或等待无关的外部依赖。
"""

import argparse
import asyncio
import re

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from procurement_assistant.business.config.settings import AppEnvironment, AppSettings
from procurement_assistant.core.delegates.database.connection_types import OpenGaussConnection
from procurement_assistant.core.delegates.database.opengauss import OpenGaussDatabaseDelegate
from procurement_assistant.core.domain.errors import ConfigurationError
from procurement_assistant.core.shared.clock import SystemClock

_REASON_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


def _parse_args() -> argparse.Namespace:
    """解析少量、不会承载 SQL 的管理参数。"""

    parser = argparse.ArgumentParser(description="将部署前活动采购场景标记为 expired")
    parser.add_argument(
        "--reason",
        default="deployment",
        help="写入场景 end_reason 的审计原因，只允许字母、数字和 . _ : -",
    )
    return parser.parse_args()


async def expire_active_scenarios(reason: str) -> int:
    """读取生产配置并通过 Database Delegate 执行一次原子过期。"""

    settings = AppSettings()
    if settings.app_env != AppEnvironment.PRODUCTION:
        raise ConfigurationError("场景过期命令要求 APP_ENV=production")
    if settings.database_dsn is None:
        raise ConfigurationError("场景过期命令缺少 DATABASE_DSN")
    if not _REASON_PATTERN.fullmatch(reason):
        raise ConfigurationError("--reason 格式不合法")

    # 管理命令与主服务使用同一种字典行连接池，保证共用 Database Delegate 时类型和
    # 运行行为一致，而不是另造一个只在发布脚本中出现的 tuple 行变体。
    pool = AsyncConnectionPool[OpenGaussConnection](
        conninfo=settings.database_dsn.get_secret_value(),
        kwargs={"row_factory": dict_row},
        min_size=1,
        max_size=1,
        open=False,
    )
    await pool.open()
    try:
        database = OpenGaussDatabaseDelegate(pool=pool, clock=SystemClock())
        return await database.expire_active_scenarios(reason)
    finally:
        await pool.close()


def main() -> None:
    """命令行入口，输出处理数量供发布日志记录。"""

    args = _parse_args()
    count = asyncio.run(expire_active_scenarios(args.reason))
    print(f"expired_active_scenarios={count}")


if __name__ == "__main__":  # pragma: no cover - 由部署脚本调用
    main()
