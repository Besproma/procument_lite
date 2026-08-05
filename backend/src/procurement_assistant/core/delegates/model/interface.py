"""Core 与 Business 之间的通用模型调用接口。"""

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from procurement_assistant.core.delegates.common.call_context import DelegateCallContext

OutputT = TypeVar("OutputT", bound=BaseModel)


ModelTaskId = str


class PromptProvider(Protocol):
    """根据 Business 注册的任务编号读取 Prompt。"""

    def get(self, task_id: ModelTaskId) -> str:
        """返回一个已经在启动阶段验证过的非空 Prompt。"""


class ScenarioToolDescription(BaseModel):
    """ReAct 可见的单个 Scenario Tool 描述。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str
    display_name: str
    description: str


class ScenarioRouteResult(BaseModel):
    """ReAct 的可见结果；不保存隐藏推理。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str | None = None
    clarification: str | None = Field(default=None, max_length=1000)


class ModelDelegate(Protocol):
    """模型能力边界。

    生产实现根据 ``task_id`` 从静态配置选择主模型和可选备用模型。Graph 不读取模型
    URL、名称或 Prompt 文件，也不能自行解析自由文本 JSON。
    """

    async def invoke_structured(
        self,
        *,
        task_id: ModelTaskId,
        input_data: BaseModel | dict[str, Any],
        output_type: type[OutputT],
        context: DelegateCallContext,
    ) -> OutputT:
        """调用结构化模型任务并返回已经验证的 Pydantic 对象。"""

    async def choose_scenario(
        self,
        *,
        original_user_text: str,
        tools: tuple[ScenarioToolDescription, ...],
        memory: dict[str, Any],
        context: DelegateCallContext,
    ) -> ScenarioRouteResult:
        """使用受限 ReAct 在 Scenario Tool 中选择一个场景。"""
