"""只允许选择 Scenario Tool 的顶层 ReAct 路由器。"""

from procurement_assistant.core.delegates.common.call_context import (
    DelegateCallContext,
)
from procurement_assistant.core.delegates.common.stream_events import AgentStreamSink
from procurement_assistant.core.delegates.model.interface import (
    ModelDelegate,
    ScenarioRouteResult,
)
from procurement_assistant.core.observability.models import SpanKind
from procurement_assistant.core.orchestration.runtime import ExecutionContext
from procurement_assistant.core.orchestration.scenarios import ScenarioRegistry


class ReactScenarioRouter:
    """根据自然语言从静态 Scenario Catalog 选择一个 Tool。

    生产 ModelDelegate 内部使用 LangChain 1.x 的可运行 ReAct；本类负责限制可见工具并
    校验结果仍属于当前 Catalog。Atomic Tool、Delegate 和数据库能力从不传给模型。
    """

    def __init__(
        self,
        *,
        model: ModelDelegate,
        scenarios: ScenarioRegistry,
    ) -> None:
        self._model = model
        self._scenarios = scenarios

    async def route(
        self,
        *,
        original_user_text: str,
        memory: dict[str, object],
        context: ExecutionContext,
    ) -> ScenarioRouteResult:
        """返回一个受支持场景或澄清问题。"""

        descriptions = tuple(item.model_description() for item in self._scenarios)

        async def invoke(
            call_context: DelegateCallContext,
            stream_sink: AgentStreamSink | None,
        ) -> ScenarioRouteResult:
            del stream_sink
            return await self._model.choose_scenario(
                original_user_text=original_user_text,
                tools=descriptions,
                memory=memory,
                context=call_context,
            )

        result = await context.call_delegate(
            name="react.scenario_router",
            kind=SpanKind.REACT,
            operation=invoke,
            input_data={
                "original_user_text": original_user_text,
                "memory": memory,
                "available_scenarios": [item.tool_id for item in descriptions],
            },
        )
        if result.scenario_id is not None and not self._scenarios.contains(result.scenario_id):
            # 模型即使返回了目录外字符串也不能启动任意 Graph。把它降级成澄清，而不是
            # 尝试 import 同名模块或调用通用 Agent 分发入口。
            return ScenarioRouteResult(
                scenario_id=None,
                clarification="我还不能确定要进入哪个采购场景，请再说明一下。",
            )
        return result
