"""``POST /api/v1/agent`` 的 AG-UI 输入模型。"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from procurement_assistant.core.domain.identifiers import ActionId, RunId, ThreadId
from procurement_assistant.core.protocol.base import ProtocolModel


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
    """页面按钮准确触发一个场景；具体允许值由 Business Registry 校验。"""

    type: Literal["scenario_trigger"]
    scenario_id: str = Field(min_length=1, max_length=100)


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

    # thread_id 表示“这段连续会话是谁”，同一个会话中的多轮请求保持不变。
    thread_id: ThreadId
    # run_id 表示“当前这一次请求是谁”，每点击一次按钮或发送一次文字都要生成新的值。
    run_id: RunId
    # 自然语言请求把本轮新用户消息放在这里；按钮或表单请求则必须保持空列表。
    messages: list[AGUIMessage] = Field(default_factory=list, max_length=200)
    # AG-UI 标准允许客户端提交下面三个字段，但本系统不信任客户端提供业务状态和工具。
    # 字段保留是为了兼容标准协议，校验器会要求它们为空。
    state: dict[str, Any] = Field(default_factory=dict)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    context: list[dict[str, Any]] = Field(default_factory=list)
    # forwarded_props 存放采购助手自己扩展的页面上下文、按钮和表单数据。
    forwarded_props: ForwardedProps = Field(default_factory=ForwardedProps)

    @model_validator(mode="after")
    def enforce_procurement_input_rules(self) -> "RunAgentInput":
        """完成字段级校验后，再检查多个字段组合在一起是否合法。

        ``@model_validator(mode="after")`` 是 Pydantic 的模型校验钩子。FastAPI 创建完
        RunAgentInput 后会自动调用它，调用者不需要手工执行本方法。
        """

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
