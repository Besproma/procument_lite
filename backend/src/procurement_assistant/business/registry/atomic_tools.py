"""跨场景 Atomic Tool 的显式注册位置。"""

from collections.abc import Mapping
from types import MappingProxyType

# 当前确认的两个场景没有需要跨 Graph 复用或暴露给 ReAct 的 Atomic Tool。以后新增时，
# 每个 Tool 仍使用独立文件，并在这里显式登记；Core 不需要随之修改。
ATOMIC_TOOL_REGISTRY: Mapping[str, object] = MappingProxyType({})
