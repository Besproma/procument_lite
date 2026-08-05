"""AG-UI 标准事件和通用 ``CUSTOM`` 事件信封。

所有事件都先构造成 Pydantic 模型，再交给 SSE 编码器。业务节点不能直接拼接 JSON，
这样可以保证后端与前端 Zod Schema 有稳定、可测试的契约。具体采购 payload 放在
Business 协议模块；Core 只负责承载和传输它们，不解释其中的业务字段。
"""

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from procurement_assistant.core.domain.identifiers import ActionId, RunId, ThreadId
from procurement_assistant.core.domain.lifecycle import ScenarioStatus
from procurement_assistant.core.protocol.base import ProtocolModel


class RunStartedEvent(ProtocolModel):
    """AG-UI Run 已接受并开始执行。"""

    type: Literal["RUN_STARTED"] = "RUN_STARTED"
    thread_id: ThreadId
    run_id: RunId


class RunFinishedEvent(ProtocolModel):
    """本次 Run 正常结束；不代表跨 Turn 场景一定完成。"""

    type: Literal["RUN_FINISHED"] = "RUN_FINISHED"
    thread_id: ThreadId
    run_id: RunId


class RunErrorEvent(ProtocolModel):
    """SSE 打开后发生的安全错误。"""

    type: Literal["RUN_ERROR"] = "RUN_ERROR"
    message: str = Field(max_length=1000)
    code: str = Field(min_length=1, max_length=100)


class TextMessageStartEvent(ProtocolModel):
    """助手文字消息开始。"""

    type: Literal["TEXT_MESSAGE_START"] = "TEXT_MESSAGE_START"
    message_id: str
    role: Literal["assistant"] = "assistant"


class TextMessageContentEvent(ProtocolModel):
    """助手文字消息增量。"""

    type: Literal["TEXT_MESSAGE_CONTENT"] = "TEXT_MESSAGE_CONTENT"
    message_id: str
    delta: str


class TextMessageEndEvent(ProtocolModel):
    """助手文字消息结束。"""

    type: Literal["TEXT_MESSAGE_END"] = "TEXT_MESSAGE_END"
    message_id: str


class CoreEventName(StrEnum):
    """运行引擎自己会发出的通用自定义事件名。"""

    SCENE = "procurement.scene"
    STATUS = "procurement.status"
    OPTIONS = "procurement.options"
    FORM = "procurement.form"
    ACTIONS = "procurement.actions"
    RETRY = "procurement.retry"
    AGENT_STREAM = "procurement.agent_stream"


class ScenePayload(ProtocolModel):
    """跨 Turn 场景生命周期。

    场景 ID 由后端静态 Catalog 校验，所以事件协议只要求它是一个非空字符串。这里不把
    当前两个场景写成 ``Literal``，否则以后新增 DAG 时，即使前端只需要通用展示状态，
    也必须同步修改所有协议类型。状态则来自统一生命周期枚举，避免各层重复维护字符串。
    """

    scenario_id: str = Field(min_length=1, max_length=100)
    status: ScenarioStatus
    reason: str | None = Field(default=None, max_length=100)


class StatusPayload(ProtocolModel):
    """只供展示的阶段状态；前端不得解析 text 决定业务。"""

    code: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1000)


class OptionItem(ProtocolModel):
    """单选候选。"""

    option_id: str
    label: str
    description: str | None = None


class OptionsPayload(ProtocolModel):
    """栏目等单选等待点。"""

    title: str
    action_id: ActionId
    multiple: Literal[False] = False
    options: tuple[OptionItem, ...] = Field(min_length=1)


class FormFieldType(StrEnum):
    """允许后端要求前端渲染的三类安全字段。"""

    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"


class SelectOption(ProtocolModel):
    """表单 select 字段的一项。"""

    value: str
    label: str


class FormField(ProtocolModel):
    """动态表单的一个受限字段。"""

    field_id: str
    label: str
    type: FormFieldType
    required: bool
    options: tuple[SelectOption, ...] = ()
    min: float | None = None
    max: float | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_options(self) -> "FormField":
        """只有 select 可以携带候选，避免 payload 演变成任意组件协议。"""

        if self.type == FormFieldType.SELECT and not self.options:
            raise ValueError("select 字段必须提供 options")
        if self.type != FormFieldType.SELECT and self.options:
            raise ValueError("非 select 字段不能提供 options")
        return self


class FormPayload(ProtocolModel):
    """需要用户填写的结构化表单。"""

    title: str
    action_id: ActionId
    fields: tuple[FormField, ...] = Field(min_length=1)
    submit_label: str = "继续"


class ActionView(ProtocolModel):
    """服务端已经签发的一次性按钮。"""

    action_id: ActionId
    kind: str = Field(min_length=1, max_length=100)
    label: str
    style: Literal["primary", "default", "danger"] = "default"


class ActionsPayload(ProtocolModel):
    """同一等待点的一组互斥 Action。"""

    title: str
    group_id: str
    actions: tuple[ActionView, ...] = Field(min_length=1)


class RetryPayload(ProtocolModel):
    """自动重试仍失败后签发的用户重试入口。"""

    action_id: ActionId
    error_code: str
    message: str
    label: str = "重试"


class AgentStreamPayload(ProtocolModel):
    """外围 Agent 明确允许展示的流式片段。"""

    call_id: str
    delegate_id: str
    attempt: int = Field(ge=1, le=2)
    stream_sequence: int = Field(ge=1)
    kind: Literal["progress", "text_delta", "status"]
    content: str


class ProcurementEventValue[PayloadT: ProtocolModel](ProtocolModel):
    """所有业务 CUSTOM 事件共享的通用信封。"""

    schema_: Literal["procurement-ui-v1"] = Field(
        default="procurement-ui-v1", serialization_alias="schema", validation_alias="schema"
    )
    thread_id: ThreadId
    run_id: RunId
    event_id: str
    sequence: int = Field(ge=1)
    payload: PayloadT


class ProcurementCustomEvent[PayloadT: ProtocolModel](ProtocolModel):
    """AG-UI ``CUSTOM`` 事件；名称和 payload 由装配进来的业务层决定。"""

    type: Literal["CUSTOM"] = "CUSTOM"
    name: str = Field(min_length=1, max_length=100)
    value: ProcurementEventValue[PayloadT]


AGUIEvent = (
    RunStartedEvent
    | RunFinishedEvent
    | RunErrorEvent
    | TextMessageStartEvent
    | TextMessageContentEvent
    | TextMessageEndEvent
    | ProcurementCustomEvent[ProtocolModel]
)
