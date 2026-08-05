"""Graph 等待用户选择、填写或确认时使用的稳定模型。"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from procurement_assistant.core.protocol.events import FormField


class ActionInputSchemaId(str):
    """Action 输入模型的静态标识。

    这里使用普通字符串子类而不是运行时 import 路径。Graph Runner 只允许从代码中的静态
    ``ACTION_INPUT_MODELS`` 查找模型，用户和数据库都不能要求加载任意 Python 类。
    """


ActionOperation = str

# 下面三个操作由 Core 自己处理，因此可以由 Core 固定。智能分流中的“换一批”、
# “自行采购”等操作全部由 Business 注册，Core 不知道也不需要知道它们的含义。
RETRY_OPERATION = "retry"
CONFIRM_SCENE_SWITCH_OPERATION = "confirm_scene_switch"
CANCEL_SCENE_SWITCH_OPERATION = "cancel_scene_switch"


class PendingActionDefinition(BaseModel):
    """在 Checkpoint 中预先保存的一次性 Action 定义。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    kind: str = Field(min_length=1, max_length=100)
    input_schema_id: str
    label: str
    style: Literal["primary", "default", "danger"] = "default"
    payload: dict[str, Any] = Field(default_factory=dict)


class OptionDefinition(BaseModel):
    """Options 等待点的一项，不依赖外围栏目名称反查。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str
    label: str
    description: str | None = None


class BaseWaitRequest(BaseModel):
    """所有等待点共享的持久化字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wait_group_id: str
    created_at: datetime
    expires_at: datetime


class FormWaitRequest(BaseWaitRequest):
    """等待用户填写一个受限表单。"""

    kind: Literal["form"] = "form"
    title: str
    action: PendingActionDefinition
    fields: tuple[FormField, ...] = Field(min_length=1)
    submit_label: str = "继续"


class OptionsWaitRequest(BaseWaitRequest):
    """等待用户从已保存在 Checkpoint 的候选中选择一个。"""

    kind: Literal["options"] = "options"
    title: str
    action: PendingActionDefinition
    options: tuple[OptionDefinition, ...] = Field(min_length=1)


class ActionsWaitRequest(BaseWaitRequest):
    """等待用户选择一组互斥按钮中的一个。"""

    kind: Literal["actions"] = "actions"
    title: str
    actions: tuple[PendingActionDefinition, ...] = Field(min_length=1)


class ConfirmationWaitRequest(BaseWaitRequest):
    """场景切换等需要确认/取消的等待点。"""

    kind: Literal["confirmation"] = "confirmation"
    title: str
    target_scenario_id: str
    previous_wait_group_id: str | None = None
    original_user_text: str
    actions: tuple[PendingActionDefinition, ...] = Field(min_length=2, max_length=2)


WaitRequest = Annotated[
    FormWaitRequest | OptionsWaitRequest | ActionsWaitRequest | ConfirmationWaitRequest,
    Field(discriminator="kind"),
]


def actions_from_wait_request(wait_request: WaitRequest) -> tuple[PendingActionDefinition, ...]:
    """统一取得等待点签发的全部 Action。

    该函数让数据库运行器无需通过 ``hasattr`` 或反射判断具体等待类型，保持显式分支并
    让新增等待类型时由类型检查及时提醒开发者补充处理。
    """

    if isinstance(wait_request, (FormWaitRequest, OptionsWaitRequest)):
        return (wait_request.action,)
    return wait_request.actions
