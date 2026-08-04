"""Scenario Graph 的启动、恢复、中断和 UI 事件协调。"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from langgraph.types import Command
from pydantic import BaseModel, TypeAdapter

from procurement_assistant.delegates.database.interface import (
    ActionRecord,
    DatabaseDelegate,
    ScenarioRecord,
)
from procurement_assistant.domain.errors import (
    DelegateTimeoutError,
    DelegateUnavailableError,
    ProcurementAssistantError,
    RunDeadlineExceededError,
)
from procurement_assistant.domain.lifecycle import InputSource, ScenarioStatus
from procurement_assistant.observability.models import SpanKind
from procurement_assistant.orchestration.action_inputs import (
    GraphResumeInput,
    validate_action_values,
)
from procurement_assistant.orchestration.actions import (
    ActionOperation,
    ActionsWaitRequest,
    ConfirmationWaitRequest,
    FormWaitRequest,
    OptionsWaitRequest,
    WaitRequest,
)
from procurement_assistant.orchestration.catalog.catalog import ScenarioCatalogItem
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.orchestration.wait_factory import WaitRequestFactory
from procurement_assistant.protocol.events import (
    ActionKind,
    ActionsPayload,
    ActionView,
    FormPayload,
    OptionItem,
    OptionsPayload,
    ProcurementEventName,
    RetryPayload,
    ScenePayload,
)
from procurement_assistant.shared.clock import Clock
from procurement_assistant.shared.ids import IdGenerator

_WAIT_REQUEST_ADAPTER: TypeAdapter[WaitRequest] = TypeAdapter(WaitRequest)
_LOGGER = logging.getLogger(__name__)


class GraphExecutionResult(BaseModel):
    """Graph Runner 返回给应用层的稳定结果。"""

    scenario_instance_id: str
    scenario_id: str
    status: ScenarioStatus
    interrupted: bool
    state: dict[str, Any]


class GraphRunner:
    """运行静态 Catalog 对应的已编译 LangGraph。"""

    def __init__(
        self,
        *,
        database: DatabaseDelegate,
        catalog: Mapping[str, ScenarioCatalogItem],
        graphs: Mapping[str, Any],
        clock: Clock,
        ids: IdGenerator,
        checkpoint_ttl_hours: int,
        waits: WaitRequestFactory,
    ) -> None:
        self._database = database
        self._catalog = catalog
        self._graphs = graphs
        self._clock = clock
        self._ids = ids
        self._checkpoint_ttl = timedelta(hours=checkpoint_ttl_hours)
        self._waits = waits

    async def start(
        self,
        *,
        scenario_id: str,
        input_source: InputSource,
        original_user_text: str | None,
        context: ExecutionContext,
    ) -> GraphExecutionResult:
        """创建场景记录和初始 State，再执行到完成或首个 Interrupt。"""

        item = self._catalog[scenario_id]
        scenario_instance_id = self._ids.new("scenario")
        now = self._clock.now()
        record = ScenarioRecord(
            scenario_instance_id=scenario_instance_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            scenario_id=scenario_id,
            input_source=input_source,
            status=ScenarioStatus.RUNNING,
            started_at=now,
            updated_at=now,
            expires_at=now + self._checkpoint_ttl,
        )
        try:
            await context.call_database(
                name="database.scenario.start",
                operation=lambda: self._database.start_scenario(record),
                input_data=record,
            )
            await context.call_database(
                name="database.run.bind_scenario",
                operation=lambda: self._database.bind_run_to_scenario(
                    context.run_id,
                    scenario_instance_id,
                ),
                input_data={
                    "run_id": context.run_id,
                    "scenario_instance_id": scenario_instance_id,
                },
            )
            async with context.trace.start_span(
                kind=SpanKind.SCENARIO,
                name=f"scenario_tool.{scenario_id}",
                target=scenario_id,
                input_json={
                    "input_source": input_source,
                    "original_user_text": original_user_text,
                    "page_context": context.page_context,
                },
            ) as span:
                initial_state = item.tool.create_initial_state(
                    scenario_instance_id=scenario_instance_id,
                    input_source=input_source,
                    original_user_text=original_user_text,
                    page_context=context.page_context,
                )
                span.set_output(initial_state)
            await context.events.custom(
                ProcurementEventName.SCENE,
                ScenePayload(scenario_id=scenario_id, status=ScenarioStatus.RUNNING),
            )
        except asyncio.CancelledError as error:
            # 客户端断线时仍尽力把已经创建的场景标为 aborted；shield 防止当前取消信号
            # 立刻打断补偿写入，避免留下活动指针。它只执行收尾，不会恢复业务调用。
            failure = self._classify_cancellation(error, context)
            await asyncio.shield(self._abort_after_failure(record, failure, context))
            raise
        except Exception as error:
            # 场景指针已经写入后，任何初始化失败都必须解除活动状态，否则用户下一次
            # 请求会永远看到一个没有可恢复 Checkpoint 的 running 场景。
            await self._abort_after_failure(record, error, context)
            raise
        return await self._execute(
            scenario=record,
            graph_input=initial_state,
            context=context,
        )

    async def resume(
        self,
        *,
        scenario: ScenarioRecord,
        action: ActionRecord,
        submitted_values: dict[str, Any],
        context: ExecutionContext,
    ) -> GraphExecutionResult:
        """验证 Action 值并从最后成功 Checkpoint 恢复。"""

        validated_values = validate_action_values(
            action.input_schema_id,
            submitted_values,
            action_payload=action.payload,
        )
        operation = ActionOperation(action.kind)
        await context.events.custom(
            ProcurementEventName.SCENE,
            ScenePayload(scenario_id=scenario.scenario_id, status=ScenarioStatus.RUNNING),
        )
        return await self._execute(
            scenario=scenario,
            # 用户重试不是 LangGraph interrupt 的回答。上一 Run 在节点异常时已经留下
            # 最后成功 Checkpoint，传 None 会从失败任务继续；其他 Action 才使用
            # Command(resume=...) 回答 Graph 的 interrupt。
            graph_input=(
                None
                if operation == ActionOperation.RETRY
                else Command(
                    resume=GraphResumeInput(
                        operation=operation,
                        values=validated_values,
                    ).model_dump(mode="json")
                )
            ),
            context=context,
        )

    async def _execute(
        self,
        *,
        scenario: ScenarioRecord,
        graph_input: Any,
        context: ExecutionContext,
    ) -> GraphExecutionResult:
        """执行 Graph，并保证所有异常路径都会结束或暂停场景。

        Graph 成功返回不代表本次处理已经完成：后面还要校验 Interrupt、保存 Action、
        发布 UI 事件并更新场景状态。整个过程都放在同一异常边界内，避免客户端恰好在
        “Graph 已返回、等待点尚未保存”期间断线后留下永久 running 的场景。
        """

        graph = self._graphs[scenario.scenario_id]
        config = {
            "configurable": {
                "thread_id": context.thread_id,
                "checkpoint_ns": scenario.scenario_instance_id,
            }
        }
        try:
            return await self._invoke_graph_and_finalize(
                graph=graph,
                config=config,
                scenario=scenario,
                graph_input=graph_input,
                context=context,
            )
        except (DelegateTimeoutError, DelegateUnavailableError) as error:
            # 两次自动尝试都失败后不丢弃场景。LangGraph 已把失败节点之前的状态保存为
            # Checkpoint；这里签发一个数据库一次性 Retry Action，用户点击后用 None
            # 重新调用同一个 Graph，从失败任务继续。协议/业务/配置错误不进入此分支。
            try:
                return await self._pause_for_user_retry(
                    scenario=scenario,
                    error=error,
                    context=context,
                )
            except asyncio.CancelledError as pause_error:
                # 取消可能发生在保存 Retry Action 或发送 Retry 事件期间。此时等待点未必
                # 完整，不能保留为 waiting；使用 shield 让短补偿写入有机会完成。
                failure = self._classify_cancellation(pause_error, context)
                await asyncio.shield(self._abort_after_failure(scenario, failure, context))
                raise
            except Exception as pause_error:
                await self._abort_after_failure(scenario, pause_error, context)
                raise
        except asyncio.CancelledError as error:
            failure = self._classify_cancellation(error, context)
            await asyncio.shield(self._abort_after_failure(scenario, failure, context))
            raise
        except ProcurementAssistantError as error:
            # 普通用户输入错误通常已在入口消费前拦截。若 Graph 内部仍发现状态与
            # Checkpoint 不一致，继续保留 waiting 会留下已消费且无法再次提交的等待点，
            # 因此把该异常路径安全终止，避免会话永久卡死。
            await self._abort_after_failure(scenario, error, context)
            raise
        except Exception as error:
            await self._abort_after_failure(scenario, error, context)
            raise

    async def _invoke_graph_and_finalize(
        self,
        *,
        graph: Any,
        config: dict[str, Any],
        scenario: ScenarioRecord,
        graph_input: Any,
        context: ExecutionContext,
    ) -> GraphExecutionResult:
        """运行一次 Graph，并把结果完整落成等待点或场景终态。

        本方法不自行吞掉异常，统一交给 ``_execute`` 决定用户重试还是终止场景。这样
        Graph 异常、Checkpoint 解析异常、数据库异常和事件发送取消都遵循同一套收尾
        规则，不会因异常发生位置不同而留下不同的半成品。
        """

        async with context.trace.start_span(
            kind=SpanKind.SCENARIO,
            name=f"scenario.{scenario.scenario_id}",
            target=scenario.scenario_id,
            input_json=graph_input,
        ) as scenario_span:
            async with context.trace.start_span(
                kind=SpanKind.GRAPH,
                name=f"graph.{scenario.scenario_id}",
                target=scenario.scenario_id,
                input_json=graph_input,
            ) as graph_span:
                raw_result = await graph.ainvoke(
                    graph_input,
                    config=config,
                    context=context,
                )
                graph_span.set_output(raw_result)
            scenario_span.set_output(raw_result)

        result_mapping = self._as_mapping(raw_result)
        interrupt_values = result_mapping.pop("__interrupt__", ())
        if interrupt_values:
            first_interrupt = interrupt_values[0]
            raw_wait = getattr(first_interrupt, "value", first_interrupt)
            wait_request = _WAIT_REQUEST_ADAPTER.validate_python(raw_wait)
            await context.call_database(
                name="database.wait_request.save",
                operation=lambda: self._database.save_wait_request(
                    user_id=context.user_id,
                    thread_id=context.thread_id,
                    scenario_instance_id=scenario.scenario_instance_id,
                    wait_request=wait_request,
                ),
                input_data=wait_request,
            )
            await self.publish_wait_request(wait_request, context)
            await context.call_database(
                name="database.scenario.update_status",
                operation=lambda: self._database.update_scenario_status(
                    scenario.scenario_instance_id,
                    ScenarioStatus.WAITING,
                ),
                input_data={
                    "scenario_instance_id": scenario.scenario_instance_id,
                    "status": ScenarioStatus.WAITING,
                },
            )
            await context.events.custom(
                ProcurementEventName.SCENE,
                ScenePayload(scenario_id=scenario.scenario_id, status=ScenarioStatus.WAITING),
            )
            return GraphExecutionResult(
                scenario_instance_id=scenario.scenario_instance_id,
                scenario_id=scenario.scenario_id,
                status=ScenarioStatus.WAITING,
                interrupted=True,
                state=result_mapping,
            )

        state_status = ScenarioStatus(result_mapping.get("status", ScenarioStatus.COMPLETED))
        final_status = state_status if state_status.is_terminal else ScenarioStatus.COMPLETED
        await context.call_database(
            name="database.scenario.update_status",
            operation=lambda: self._database.update_scenario_status(
                scenario.scenario_instance_id,
                final_status,
            ),
            input_data={
                "scenario_instance_id": scenario.scenario_instance_id,
                "status": final_status,
            },
        )
        await context.events.custom(
            ProcurementEventName.SCENE,
            ScenePayload(scenario_id=scenario.scenario_id, status=final_status),
        )
        return GraphExecutionResult(
            scenario_instance_id=scenario.scenario_instance_id,
            scenario_id=scenario.scenario_id,
            status=final_status,
            interrupted=False,
            state=result_mapping,
        )

    async def _pause_for_user_retry(
        self,
        *,
        scenario: ScenarioRecord,
        error: DelegateUnavailableError | DelegateTimeoutError,
        context: ExecutionContext,
    ) -> GraphExecutionResult:
        """把可恢复外围失败转换成新的、可持久化用户重试等待点。"""

        wait_request = self._waits.retry(capability="当前步骤")
        await context.call_database(
            name="database.wait_request.save_retry",
            operation=lambda: self._database.save_wait_request(
                user_id=context.user_id,
                thread_id=context.thread_id,
                scenario_instance_id=scenario.scenario_instance_id,
                wait_request=wait_request,
            ),
            input_data=wait_request,
        )
        await self.publish_wait_request(wait_request, context)
        retry_action = wait_request.actions[0]
        await context.events.custom(
            ProcurementEventName.RETRY,
            RetryPayload(
                action_id=retry_action.action_id,
                error_code=error.code,
                message="暂时没有处理成功，可以从当前步骤重试。",
                label=retry_action.label,
            ),
        )
        await context.call_database(
            name="database.scenario.update_status",
            operation=lambda: self._database.update_scenario_status(
                scenario.scenario_instance_id,
                ScenarioStatus.WAITING,
                reason=error.code,
            ),
            input_data={
                "scenario_instance_id": scenario.scenario_instance_id,
                "status": ScenarioStatus.WAITING,
                "reason": error.code,
            },
        )
        await context.events.custom(
            ProcurementEventName.SCENE,
            ScenePayload(
                scenario_id=scenario.scenario_id,
                status=ScenarioStatus.WAITING,
                reason=error.code,
            ),
        )

        # 这里不能调用 ``graph.aget_state(config)`` 读取快照。我们用非空
        # ``checkpoint_ns`` 隔离同一 thread 下的不同场景；LangGraph 1.2 会把传给
        # ``aget_state`` 的非空命名空间解释成“查找同名 Subgraph”，而场景实例实际是
        # 根 Graph 的存储命名空间，因此会抛出 ``Subgraph ... not found``。
        #
        # 用户重试所需的真实状态已经由 Checkpointer 保存，下一次 ``ainvoke(None)`` 会
        # 从那里恢复。``GraphExecutionResult.state`` 只是本次运行的内部结果摘要，不参与
        # 持久化、恢复或前端协议，所以失败暂停时返回空字典最安全：既不依赖 LangGraph
        # 的内部配置键，也不会误把不完整状态当成业务结果。
        return GraphExecutionResult(
            scenario_instance_id=scenario.scenario_instance_id,
            scenario_id=scenario.scenario_id,
            status=ScenarioStatus.WAITING,
            interrupted=True,
            state={},
        )

    async def publish_wait_request(
        self, wait_request: WaitRequest, context: ExecutionContext
    ) -> None:
        """把持久化等待点转换成唯一对应的采购 UI 事件。

        场景切换确认由应用分发层创建，不经过业务 Graph，但仍复用本方法和完全相同的
        Action/事件契约，避免出现第二套按钮协议。
        """

        if isinstance(wait_request, FormWaitRequest):
            await context.events.custom(
                ProcurementEventName.FORM,
                FormPayload(
                    title=wait_request.title,
                    action_id=wait_request.action.action_id,
                    fields=wait_request.fields,
                    submit_label=wait_request.submit_label,
                ),
            )
            return
        if isinstance(wait_request, OptionsWaitRequest):
            await context.events.custom(
                ProcurementEventName.OPTIONS,
                OptionsPayload(
                    title=wait_request.title,
                    action_id=wait_request.action.action_id,
                    options=tuple(
                        OptionItem(
                            option_id=option.option_id,
                            label=option.label,
                            description=option.description,
                        )
                        for option in wait_request.options
                    ),
                ),
            )
            return
        if isinstance(wait_request, (ActionsWaitRequest, ConfirmationWaitRequest)):
            await context.events.custom(
                ProcurementEventName.ACTIONS,
                ActionsPayload(
                    title=wait_request.title,
                    group_id=wait_request.wait_group_id,
                    actions=tuple(
                        ActionView(
                            action_id=action.action_id,
                            kind=ActionKind(action.kind),
                            label=action.label,
                            style=action.style,
                        )
                        for action in wait_request.actions
                    ),
                ),
            )
            return
        raise TypeError(f"不支持的 WaitRequest：{type(wait_request).__name__}")

    async def _abort_after_failure(
        self,
        scenario: ScenarioRecord,
        error: BaseException,
        context: ExecutionContext,
    ) -> None:
        """失败后尽力清理场景；清理失败不能覆盖原始异常。

        这是一个补偿动作，不和外围调用共享事务。数据库更新与 UI 事件分别失败时都只
        写受控日志，避免异常处理本身再次把 SSE 变成未捕获错误；下一次快照仍会依据
        数据库实际状态判断能否恢复。
        """

        reason = getattr(error, "code", "INTERNAL_ERROR")
        try:
            await context.call_database(
                name="database.scenario.abort_after_failure",
                operation=lambda: self._database.update_scenario_status(
                    scenario.scenario_instance_id,
                    ScenarioStatus.ABORTED,
                    reason,
                ),
                input_data={
                    "scenario_instance_id": scenario.scenario_instance_id,
                    "status": ScenarioStatus.ABORTED,
                    "reason": reason,
                },
            )
        except Exception:
            _LOGGER.exception(
                "场景失败收尾落库失败，scenario_instance_id=%s",
                scenario.scenario_instance_id,
            )
        try:
            await context.events.custom(
                ProcurementEventName.SCENE,
                ScenePayload(
                    scenario_id=scenario.scenario_id,
                    status=ScenarioStatus.ABORTED,
                    reason=reason,
                ),
            )
        except Exception:
            _LOGGER.exception(
                "场景失败收尾事件发送失败，scenario_instance_id=%s",
                scenario.scenario_instance_id,
            )

    @staticmethod
    def _classify_cancellation(
        error: asyncio.CancelledError,
        context: ExecutionContext,
    ) -> BaseException:
        """区分客户端断线取消和总截止时间触发的内部取消。

        ``asyncio.timeout`` 在被包裹协程内部表现为 ``CancelledError``，离开超时上下文
        后才转换成 ``TimeoutError``。Graph Runner 必须在内部取消阶段就完成场景补偿，
        因此通过同一个单调时钟 deadline 判断原因，让场景的 ``end_reason`` 与最终 Run
        错误码保持一致；普通浏览器断线仍沿用原始取消异常。
        """

        if context.deadline.remaining_seconds <= 0:
            return RunDeadlineExceededError("本次处理时间已超过系统上限，请重试")
        return error

    @staticmethod
    def _as_mapping(raw_result: Any) -> dict[str, Any]:
        """把 LangGraph 返回值复制成可安全修改的字典。"""

        if isinstance(raw_result, BaseModel):
            return raw_result.model_dump()
        if isinstance(raw_result, dict):
            return dict(raw_result)
        raise TypeError(f"LangGraph 返回了不支持的结果类型：{type(raw_result).__name__}")
