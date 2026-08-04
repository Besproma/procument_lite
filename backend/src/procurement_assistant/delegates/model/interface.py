"""业务节点可使用的模型接口。"""

from enum import StrEnum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from procurement_assistant.delegates.common.call_context import DelegateCallContext

OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelTaskId(StrEnum):
    """Prompt Catalog 中允许的模型任务。"""

    SCENARIO_ROUTER = "scenario_router"
    PURCHASE_FIELD_EXTRACTION = "purchase_field_extraction"
    PRODUCT_SEARCH_TERMS = "product_search_terms"
    MEMORY_UPDATE = "memory_update"


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
