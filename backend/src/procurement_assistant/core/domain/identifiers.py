"""系统标识类型与生成规则。"""

from typing import Annotated
from uuid import uuid4

from pydantic import StringConstraints

# 用户 ID 来自页面上下文，允许公司常见的字母、数字和少量分隔符，但绝不允许空白、
# 路径分隔符或控制字符。其他 ID 均由本系统生成，使用相同的安全字符集合。
UserId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@-]+$"),
]
ThreadId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"),
]
RunId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"),
]
ScenarioInstanceId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"),
]
ActionId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"),
]
TraceId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"),
]


def new_identifier(prefix: str) -> str:
    """生成不包含业务数据的不可预测标识。

    前缀只帮助开发和排障时辨认对象类型，UUID 中不编码用户、场景或节点信息，避免
    日志中的标识间接泄露业务内容。
    """

    return f"{prefix}_{uuid4().hex}"
