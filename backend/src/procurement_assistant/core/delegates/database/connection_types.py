"""OpenGauss 连接池在各数据库 Delegate 之间共享的类型。

Psycopg 的连接与连接池都带有“每行返回什么形状”的泛型参数。LangGraph 官方
PostgreSQL Checkpointer 要求字典行；主数据库 Delegate 和 Trace 也按字段名读取结果，
因此整个应用统一使用字典行连接池。把类型集中在这里可以防止某个适配器误收默认的
tuple 行连接池，直到生产运行才暴露不兼容。
"""

from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

type OpenGaussRow = dict[str, Any]
type OpenGaussConnection = AsyncConnection[OpenGaussRow]
type OpenGaussPool = AsyncConnectionPool[OpenGaussConnection]
