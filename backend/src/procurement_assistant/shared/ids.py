"""统一标识生成器。"""

from typing import Protocol

from procurement_assistant.domain.identifiers import new_identifier


class IdGenerator(Protocol):
    """允许测试提供确定性 ID 的接口。"""

    def new(self, prefix: str) -> str:
        """生成带对象类型前缀的不可预测标识。"""


class UuidIdGenerator:
    """生产环境 UUID 标识生成器。"""

    def new(self, prefix: str) -> str:
        """生成 UUID 标识。"""

        return new_identifier(prefix)
