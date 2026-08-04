"""OpenAI 兼容 Model Delegate。

正式模型协议采用 OpenAI 兼容 Chat Completions 接口，具体 base_url、模型名和凭据由
配置提供。LangChain 负责模型、结构化输出和 ReAct 运行；业务 Graph 不依赖其具体对象。
"""

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, SecretStr

from procurement_assistant.config import AppSettings
from procurement_assistant.delegates.common.call_context import DelegateCallContext
from procurement_assistant.delegates.model.interface import (
    ModelDelegate,
    ModelTaskId,
    ScenarioRouteResult,
    ScenarioToolDescription,
)
from procurement_assistant.domain.errors import (
    ConfigurationError,
    DelegateContractError,
    NonRetryableDelegateError,
    ProcurementAssistantError,
    RetryableDelegateError,
)
from procurement_assistant.prompts.catalog import load_prompt

OutputT = TypeVar("OutputT", bound=BaseModel)


def _is_retryable_model_error(error: BaseException) -> bool:
    """判断 LangChain/OpenAI 兼容调用是否属于临时传输故障。

    ChatOpenAI 往往把 HTTPX 异常包装成 SDK 异常，因此只捕获最外层
    ``TimeoutError`` 会漏掉限流、连接失败和 5xx。这里沿异常原因链检查标准网络异常，
    并读取 SDK 普遍提供的 ``status_code``；不依赖某个 OpenAI 兼容供应商的私有类名。
    """

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(
            current,
            (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError),
        ):
            return True

        status_code = getattr(current, "status_code", None)
        if not isinstance(status_code, int):
            response = getattr(current, "response", None)
            status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and (status_code in {408, 425, 429} or status_code >= 500):
            return True

        current = current.__cause__ or current.__context__
    return False


class OpenAICompatibleModelDelegate(ModelDelegate):
    """通过 LangChain 接入 OpenAI 兼容模型。

    ChatOpenAI 的 import 放在初始化方法内，原因是生产代码在未安装依赖时仍能被静态工具
    检查，而本地 Fake Composition Root 不需要创建真实模型客户端。生产启动时若配置缺失
    会由 ``AppSettings`` 或本类明确报错，而不是默默使用 Fake。
    """

    def __init__(self, settings: AppSettings) -> None:
        if settings.model_base_url is None or settings.model_name is None:
            raise ValueError("OpenAI 兼容模型缺少 MODEL_BASE_URL 或 MODEL_NAME")
        self._settings = settings
        self._primary = self._create_chat_model(
            base_url=settings.model_base_url,
            model_name=settings.model_name,
            api_key=settings.model_api_key,
        )
        # 备用模型只有三项配置同时存在时才创建。没有备用模型时，第二次尝试仍使用主
        # 模型，不能为了“看起来支持 fallback”而调用不存在的配置。
        self._fallback = None
        if (
            settings.fallback_model_base_url is not None
            and settings.fallback_model_name is not None
        ):
            self._fallback = self._create_chat_model(
                base_url=settings.fallback_model_base_url,
                model_name=settings.fallback_model_name,
                api_key=settings.fallback_model_api_key,
            )

    @staticmethod
    def _create_chat_model(*, base_url: str, model_name: str, api_key: SecretStr | None) -> Any:
        """创建一个 OpenAI 兼容 ChatOpenAI 客户端。

        凭据保持 ``SecretStr`` 直到交给 SDK，避免为了构造客户端提前解包成普通字符串，
        从而降低它被调试输出或异常上下文意外记录的风险。部分内网兼容服务无需鉴权；
        此时传空的 SecretStr，而不是让 SDK回退读取进程里的其他 OpenAI 环境变量。
        """

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - 依赖安装由开发环境负责
            raise RuntimeError("未安装 langchain-openai，无法创建生产模型 Delegate") from exc
        return ChatOpenAI(
            base_url=base_url,
            api_key=api_key or SecretStr(""),
            model=model_name,
            streaming=True,
        )

    def _model_for_attempt(self, attempt: int) -> Any:
        """第二次尝试仅在备用模型存在时选择备用模型。"""

        return self._fallback if attempt > 1 and self._fallback is not None else self._primary

    async def invoke_structured(
        self,
        *,
        task_id: ModelTaskId,
        input_data: BaseModel | dict[str, Any],
        output_type: type[OutputT],
        context: DelegateCallContext,
    ) -> OutputT:
        """加载固定 Prompt、请求结构化结果并再次 Pydantic 校验。"""

        prompt = load_prompt(task_id)
        model = self._model_for_attempt(context.attempt)
        payload = (
            input_data.model_dump(mode="json") if isinstance(input_data, BaseModel) else input_data
        )
        try:
            structured_model = model.with_structured_output(output_type)
            result = await structured_model.ainvoke(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        # OpenAI Chat Completions 的普通文本 content 不能直接放 Python
                        # dict。统一转成 JSON 文本还能保留中文和明确字段边界。
                        "content": json.dumps(payload, ensure_ascii=False, default=str),
                    },
                ]
            )
            return output_type.model_validate(result)
        except ProcurementAssistantError:
            raise
        except Exception as exc:
            if _is_retryable_model_error(exc):
                raise RetryableDelegateError(f"模型任务 {task_id.value} 暂时不可用") from exc
            if isinstance(exc, ValueError):
                raise DelegateContractError(f"模型任务 {task_id.value} 返回结构不合法") from exc
            # 其余 4xx、鉴权、业务拒绝和无法分类的 SDK 错误不自动重放。错误正文、URL
            # 和凭据只保留在受控日志链中，不进入 Graph 或用户响应。
            raise NonRetryableDelegateError(f"模型任务 {task_id.value} 执行失败") from exc

    async def choose_scenario(
        self,
        *,
        original_user_text: str,
        tools: tuple[ScenarioToolDescription, ...],
        memory: dict[str, Any],
        context: DelegateCallContext,
    ) -> ScenarioRouteResult:
        """运行一个只暴露 Scenario Tool 的 LangChain ReAct Agent。

        Tool 函数只返回静态 ``tool_id``，不执行任何采购能力。服务端随后还会用 Catalog
        再次校验 tool_id；即使模型输出目录外字符串，也无法启动未知 Graph。
        """

        try:
            from langchain.agents import create_agent
            from langchain_core.tools import StructuredTool
            from pydantic import BaseModel, ConfigDict
        except ImportError as exc:  # pragma: no cover - 依赖安装由开发环境负责
            raise ConfigurationError("未安装 LangChain 1.x，无法创建 ReAct 路由器") from exc

        class EmptyToolInput(BaseModel):
            """handoff Tool 不接收模型自由参数。"""

            model_config = ConfigDict(extra="forbid")

        available_tools: list[Any] = []
        for description in tools:
            tool_id = description.tool_id

            def create_handoff(selected_tool_id: str) -> Any:
                """为当前目录项固定绑定 Tool ID，避免循环闭包全部指向最后一项。"""

                async def handoff() -> str:
                    """只返回静态 ID，真正启动由服务端路由器完成。"""

                    return selected_tool_id

                return handoff

            available_tools.append(
                StructuredTool.from_function(
                    coroutine=create_handoff(tool_id),
                    name=tool_id,
                    description=description.description,
                    args_schema=EmptyToolInput,
                )
            )

        try:
            model = self._model_for_attempt(context.attempt)
            agent = create_agent(
                model=model,
                tools=available_tools,
                system_prompt=load_prompt(ModelTaskId.SCENARIO_ROUTER),
            )
            memory_text = (
                json.dumps(memory, ensure_ascii=False, default=str)
                if memory
                else "（没有可用长期记忆）"
            )
            result = await agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": f"用户原文：{original_user_text}\n辅助记忆：{memory_text}",
                        }
                    ]
                }
            )
            messages = result.get("messages", [])
            for message in reversed(messages):
                tool_calls = getattr(message, "tool_calls", None) or []
                if tool_calls:
                    selected = tool_calls[-1].get("name")
                    return ScenarioRouteResult(scenario_id=selected)
            return ScenarioRouteResult(
                clarification="我还不能确定要进入哪个采购场景，请再说明一下。"
            )
        except ProcurementAssistantError:
            raise
        except Exception as exc:
            if _is_retryable_model_error(exc):
                raise RetryableDelegateError("场景识别模型暂时不可用") from exc
            if isinstance(exc, (ValueError, TypeError, KeyError)):
                raise DelegateContractError("场景识别模型返回结构不合法") from exc
            # SDK、模型服务或 ReAct 执行器的内部异常在 Delegate 边界统一收口，Graph
            # 不依赖某个供应商的异常类型，也不会把 URL/响应正文泄露给用户。
            raise NonRetryableDelegateError("场景识别模型执行失败") from exc
