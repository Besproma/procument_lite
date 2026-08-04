"""``POST /api/v1/agent`` 的 AG-UI 输入模型。"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from procurement_assistant.domain.identifiers import ActionId, RunId, ThreadId
from procurement_assistant.protocol.base import ProtocolModel


class AGUIMessage(ProtocolModel):
    """本次 AG-UI 请求携带的一条消息。

    后端只把最后一条新用户消息作为本次自然语言输入。客户端携带的旧消息只用于兼容
    标准 AG-UI Client，服务端历史仍以 OpenGauss 为准。
    """

    id: str = Field(min_length=1, max_length=100)
    role: Literal["user", "assistant", "system", "tool"]
    content: str = Field(max_length=100_000)


class PageContext(ProtocolModel):
    """公司页面直接提供的非鉴权上下文。"""

    region_code: str | None = Field(default=None, min_length=1, max_length=64)
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)
    current_page: str | None = Field(default=None, max_length=500)


class ScenarioTriggerInput(ProtocolModel):
    """页面按钮准确触发一个已注册场景。"""

    type: Literal["scenario_trigger"]
    scenario_id: Literal["smart_routing", "knowledge_recommendation"]


class ActionInput(ProtocolModel):
    """提交服务端签发的一次性按钮。"""

    type: Literal["action"]
    action_id: ActionId
    data: dict[str, Any] = Field(default_factory=dict)


class FormSubmitInput(ProtocolModel):
    """提交服务端签发的结构化表单。"""

    type: Literal["form_submit"]
    action_id: ActionId
    values: dict[str, Any]


ProcurementInput = Annotated[
    ScenarioTriggerInput | ActionInput | FormSubmitInput,
    Field(discriminator="type"),
]


class ForwardedProps(ProtocolModel):
    """采购助手允许的全部 forwardedProps。"""

    page_context: PageContext = Field(default_factory=PageContext)
    procurement_input: ProcurementInput | None = None


class RunAgentInput(ProtocolModel):
    """采购助手当前支持的 AG-UI ``RunAgentInput`` 子集。

    标准 AG-UI 允许客户端传 tools、state 和 context，但本系统的 Tool 和业务状态只能
    由服务端决定。这里仍保留字段以兼容 Client，随后强制它们为空，防止客户端注入。
    """

    thread_id: ThreadId
    run_id: RunId
    messages: list[AGUIMessage] = Field(default_factory=list, max_length=200)
    state: dict[str, Any] = Field(default_factory=dict)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    context: list[dict[str, Any]] = Field(default_factory=list)
    forwarded_props: ForwardedProps = Field(default_factory=ForwardedProps)

    @model_validator(mode="after")
    def enforce_procurement_input_rules(self) -> "RunAgentInput":
        """阻止自然语言和结构化操作互相混用。"""

        if self.state or self.tools or self.context:
            raise ValueError("当前版本不接受客户端 state、tools 或 context")

        procurement_input = self.forwarded_props.procurement_input
        if procurement_input is None:
            if not self.messages:
                raise ValueError("自然语言 Run 必须包含用户消息")
            if self.messages[-1].role != "user":
                raise ValueError("自然语言 Run 必须以新的用户消息结尾")
            if not self.messages[-1].content.strip():
                raise ValueError("用户消息不能为空")
        elif self.messages:
            raise ValueError("按钮、Action 或 Form Run 不得同时携带 messages")

        return self

    @property
    def original_user_text(self) -> str | None:
        """返回服务器可信的本次原始用户文字。

        Scenario Tool 从这里读取原文，不接收模型自由生成的查询参数，因此知识推荐的
        精确匹配 key 不会被 ReAct 改写。
        """

        if self.forwarded_props.procurement_input is not None:
            return None
        return self.messages[-1].content
