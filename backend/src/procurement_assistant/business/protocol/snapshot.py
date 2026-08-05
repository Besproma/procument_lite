"""采购业务对会话快照的投影规则。"""

from dataclasses import dataclass
from typing import ClassVar

from procurement_assistant.business.protocol.events import BusinessEventName
from procurement_assistant.core.protocol.events import CoreEventName


@dataclass(frozen=True, slots=True)
class ProcurementSnapshotPolicy:
    """声明哪些采购 UI 事件在页面刷新后仍有展示价值。

    Core 只执行“按策略筛选并保留最新块”的通用算法，不知道商品或排队事件。以后新增
    业务事件时，只需在 Business 这里决定它是否可恢复，不需要修改 Core 会话接口。
    """

    _interactive_names: ClassVar[frozenset[str]] = frozenset(
        {
            CoreEventName.FORM.value,
            CoreEventName.OPTIONS.value,
            CoreEventName.ACTIONS.value,
            CoreEventName.RETRY.value,
        }
    )
    _restorable_names: ClassVar[frozenset[str]] = frozenset(
        {
            CoreEventName.STATUS.value,
            BusinessEventName.PRODUCTS.value,
            BusinessEventName.QUEUE.value,
        }
    )

    def is_interactive(self, event_name: str) -> bool:
        """判断刷新后是否可以保留一个仍可能有效的交互块。"""

        return event_name in self._interactive_names

    def is_restorable(self, event_name: str) -> bool:
        """判断刷新后是否保留一项最新的非交互展示块。"""

        return event_name in self._restorable_names
