"""内部事件到 AG-UI 事件的统一发射器。"""

from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from procurement_assistant.delegates.common.stream_events import AgentStreamEvent
from procurement_assistant.domain.identifiers import new_identifier
from procurement_assistant.protocol.base import ProtocolModel
from procurement_assistant.protocol.events import (
    AgentStreamPayload,
    ProcurementCustomEvent,
    ProcurementEventName,
    ProcurementEventValue,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

Event = ProtocolModel
EventSink = Callable[[Event], Awaitable[None]]
EventT = TypeVar("EventT", bound=ProtocolModel)
PayloadT = TypeVar("PayloadT", bound=ProtocolModel)


class AGUIEventEmitter:
    """一个 Run 独享的“前端消息打包器”。

    Graph 节点只需要表达“显示一段文字”或“显示一组选项”。本类把这些内容包装成统一
    AG-UI 事件，补齐 threadId、runId 和顺序号，再交给 agent.py 提供的 sink 放入队列。
    同时保留已发事件，供结果持久化和调用链统计使用。
    """

    def __init__(
        self,
        *,
        thread_id: str,
        run_id: str,
        sink: EventSink | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self._sink = sink
        self._sequence = 0
        self.events: list[Event] = []

    async def _publish(self, event: EventT) -> EventT:
        """保存事件，并通过 sink 把它送到 agent.py 的 SSE 队列。"""

        self.events.append(event)
        if self._sink is not None:
            await self._sink(event)
        return event

    def _next_sequence(self) -> int:
        """生成当前 Run 内严格递增的采购事件序号。"""

        self._sequence += 1
        return self._sequence

    async def run_started(self) -> RunStartedEvent:
        """发出 Run 开始事件。"""

        return await self._publish(RunStartedEvent(thread_id=self.thread_id, run_id=self.run_id))

    async def run_finished(self) -> RunFinishedEvent:
        """发出 Run 正常结束事件。"""

        return await self._publish(RunFinishedEvent(thread_id=self.thread_id, run_id=self.run_id))

    async def run_error(self, code: str, message: str) -> RunErrorEvent:
        """发出不包含堆栈和凭据的安全错误。"""

        return await self._publish(RunErrorEvent(code=code, message=message))

    async def text_message(
        self, content: str
    ) -> tuple[TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent]:
        """把一段助手文字拆成“开始、内容、结束”三个标准事件。

        目前内容可能一次性给出，但保持三段协议后，未来模型逐段生成文字时前端仍可以
        使用同一种事件处理方式。
        """

        message_id = new_identifier("message")
        start = await self._publish(TextMessageStartEvent(message_id=message_id))
        delta = await self._publish(TextMessageContentEvent(message_id=message_id, delta=content))
        end = await self._publish(TextMessageEndEvent(message_id=message_id))
        return start, delta, end

    async def custom(
        self,
        name: ProcurementEventName,
        payload: PayloadT,
    ) -> ProcurementCustomEvent[PayloadT]:
        """发出采购 ``CUSTOM`` 事件。

        事件信封由这里统一生成，节点只提供已经通过 Pydantic 校验的 payload，不能自行
        修改 schema、threadId、runId 或 sequence。
        """

        value = ProcurementEventValue[PayloadT](
            thread_id=self.thread_id,
            run_id=self.run_id,
            event_id=new_identifier("event"),
            sequence=self._next_sequence(),
            payload=payload,
        )
        return await self._publish(ProcurementCustomEvent(name=name, value=value))

    async def agent_stream(self, event: AgentStreamEvent) -> None:
        """仅转发允许展示的外围进度/文字/状态事件。"""

        # 内部流还包含 final_result 和 error，它们分别用于 Delegate 最终结果校验和错误
        # 分类，绝不能直接发给前端。显式分支既形成安全白名单，也让静态类型检查确认传入
        # AgentStreamPayload 的 kind 一定属于公开协议允许的三个值。
        public_kind: Literal["progress", "text_delta", "status"]
        if event.kind == "progress":
            public_kind = "progress"
        elif event.kind == "text_delta":
            public_kind = "text_delta"
        elif event.kind == "status":
            public_kind = "status"
        else:
            return
        if event.display_text is None:
            return
        await self.custom(
            ProcurementEventName.AGENT_STREAM,
            AgentStreamPayload(
                call_id=event.call_id,
                delegate_id=event.delegate_id,
                attempt=event.attempt,
                stream_sequence=event.sequence,
                kind=public_kind,
                content=event.display_text,
            ),
        )
