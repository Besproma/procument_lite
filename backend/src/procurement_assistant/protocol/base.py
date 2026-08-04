"""前后端协议模型的公共配置。"""

from pydantic import BaseModel, ConfigDict


def to_camel(field_name: str) -> str:
    """把 Python 的 snake_case 字段名转换为前端使用的 camelCase。"""

    first, *rest = field_name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ProtocolModel(BaseModel):
    """严格的 JSON 协议模型。

    Python 代码使用易读的 snake_case，序列化时统一产生 camelCase。拒绝额外字段可以
    在接口边界及时发现前后端版本不一致或恶意输入，避免数据被静默忽略。
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
