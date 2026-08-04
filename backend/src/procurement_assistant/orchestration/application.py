"""HTTP 接入层调用的 Agent 应用服务。"""

import asyncio
from functools import partial

from pydantic import BaseModel, ConfigDict

from procurement_assistant.config import AppSettings
from procurement_assistant.delegates.database.interface import (
    AdmissionStatus,
    BeginRunRequest,
    DatabaseDelegate,
    MessageRecord,
    RunAdmission,
)
from procurement_assistant.domain.errors import (
    ConcurrentRunError,
    ConfigurationError,
    DuplicateRunError,
    InvalidUserInputError,
    ProcurementAssistantError,
    RunDeadlineExceededError,
)
from procurement_assistant.domain.lifecycle import InputSource, RunStatus
from procurement_assistant.orchestration.action_inputs import validate_action_values
from procurement_assistant.orchestration.actions import ActionOperation
from procurement_assistant.orchestration.graph_runner import GraphExecutionResult, GraphRunner
from procurement_assistant.orchestration.router.react_router import ReactScenarioRouter
from procurement_assistant.orchestration.router.scene_switch import SceneSwitchCoordinator
from procurement_assistant.orchestration.runtime import ExecutionContext
from procurement_assistant.protocol.events import (
    ProcurementCustomEvent,
    TextMessageContentEvent,
)
from procurement_assistant.protocol.run_input import (
    ActionInput,
    FormSubmitInput,
    RunAgentInput,
    ScenarioTriggerInput,
)
from procurement_assistant.shared.clock import Clock
from procurement_assistant.shared.ids import IdGenerator


class ApplicationResult(BaseModel):
    """一次已接受 Run 的应用层结果。"""

    model_config = ConfigDict(extra="forbid")

    graph_result: GraphExecutionResult | None = None
    assistant_texts: tuple[str, ...] = ()


class AgentApplication:
    """协调入口幂等、场景分发、Graph Runner 和持久化收尾。

    本类不包含采购节点判断；它只决定本次输入属于按钮启动、自然语言路由、场景切换或
    Action 恢复，并保证 Run 状态与租约在成功和异常路径都正确结束。
    """

    def __init__(
        self,
        *,
        settings: AppSettings,
        database: DatabaseDelegate,
        router: ReactScenarioRouter,
        runner: GraphRunner,
        scene_switch: SceneSwitchCoordinator,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._settings = settings
        self._database = database
        self._router = router
        self._runner = runner
        self._scene_switch = scene_switch
        self._clock = clock
        self._ids = ids

    async def admit(
        self,
        *,
        user_id: str,
        request: RunAgentInput,
        trace_id: str,
    ) -> RunAdmission:
        """在 SSE 打开前完成幂等、thread 租约和可选 Action 消费。"""

        procurement_input = request.forwarded_props.procurement_input
        action_id = (
            procurement_input.action_id
            if isinstance(procurement_input, (ActionInput, FormSubmitInput))
            else None
        )
        input_type = procurement_input.type if procurement_input is not None else "natural_language"
        # 幂等优先级高于请求体内容：网络重试即使携带了损坏的旧 payload，也必须返回
        # DUPLICATE，而不能因为再次预校验失败而暴露另一种结果。
        existing_run = await self._database.get_run(
            request.run_id,
            user_id,
            request.thread_id,
        )
        if existing_run is not None:
            raise DuplicateRunError(existing_run.status.value)

        if isinstance(procurement_input, (ActionInput, FormSubmitInput)):
            # 先读取 Action 做纯校验，避免非法值在 begin_run 中被消费。最终 begin_run
            # 仍会在同一短事务里再次锁定 Action；两次读取之间若被另一个请求抢先消费，
            # 那一请求会赢，当前请求得到 ACTION_EXPIRED，不会绕过一次性约束。
            action = await self._database.get_action(
                procurement_input.action_id,
                user_id,
                request.thread_id,
            )
            submitted_values = (
                procurement_input.values
                if isinstance(procurement_input, FormSubmitInput)
                else procurement_input.data
            )
            validate_action_values(
                action.input_schema_id,
                submitted_values,
                action_payload=action.payload,
            )
            try:
                ActionOperation(action.kind)
            except ValueError as exc:
                raise ConfigurationError("服务端 Action 类型不存在") from exc
        admission = await self._database.begin_run(
            BeginRunRequest(
                run_id=request.run_id,
                thread_id=request.thread_id,
                user_id=user_id,
                trace_id=trace_id,
                input_type=input_type,
                action_id=action_id,
                lease_seconds=self._settings.thread_lease_seconds,
            )
        )
        if admission.status == AdmissionStatus.THREAD_BUSY:
            raise ConcurrentRunError("当前会话正在处理上一项操作，请稍后重试")
        if admission.status == AdmissionStatus.DUPLICATE:
            # 幂等冲突必须发生在 StreamingResponse 创建之前。若等到 ``execute`` 才
            # 抛错，HTTP 状态已经固定为 200，前端只能收到一个含义错误的 SSE 失败。
            raise DuplicateRunError(admission.run.status.value)
        return admission

    async def execute(
        self,
        *,
        user_id: str,
        request: RunAgentInput,
        admission: RunAdmission,
        context: ExecutionContext,
    ) -> ApplicationResult:
        """执行一个已经通过入口短事务的 Run。"""

        if admission.status != AdmissionStatus.ACCEPTED:
            # ``admit`` 已经把 duplicate/busy 转换成入口错误；到达这里说明 API 绕过
            # 了规定调用顺序，属于开发错误而不是用户输入错误。
            raise RuntimeError("只有已接受的 Run 才能进入应用执行阶段")

        await context.events.run_started()
        initial_event_count = len(context.events.events)
        try:
            graph_result = await self._dispatch_with_deadline(
                user_id=user_id,
                request=request,
                admission=admission,
                context=context,
            )
            assistant_texts = await self._persist_display_output(
                user_id=user_id,
                request=request,
                context=context,
                first_event_index=initial_event_count,
            )
            await context.call_database(
                name="database.run.finish",
                operation=lambda: self._database.finish_run(
                    request.run_id,
                    RunStatus.SUCCEEDED,
                ),
                input_data={"run_id": request.run_id, "status": RunStatus.SUCCEEDED},
            )
            # RUN_FINISHED 必须是成功 Run 的最后一条事件。先完成必要持久化和租约释放，
            # 可以避免客户端已经看到“成功”，后端随后却因保存失败再发送 RUN_ERROR。
            await context.events.run_finished()
            return ApplicationResult(
                graph_result=graph_result,
                assistant_texts=assistant_texts,
            )
        except asyncio.CancelledError:
            # 浏览器断开时 ASGI 服务器会取消执行任务。CancelledError 不属于普通
            # Exception，必须单独处理，否则 Run 会永久保持 running，只能等租约过期。
            # shield 给这个很短的收尾写入一次完成机会；它不会延长或恢复业务执行。
            await asyncio.shield(
                context.call_database(
                    name="database.run.finish",
                    operation=lambda: self._database.finish_run(
                        request.run_id,
                        RunStatus.FAILED,
                        "CLIENT_DISCONNECTED",
                    ),
                    input_data={
                        "run_id": request.run_id,
                        "status": RunStatus.FAILED,
                        "error_code": "CLIENT_DISCONNECTED",
                    },
                )
            )
            raise
        except ProcurementAssistantError as exc:
            # Python 会在离开 ``except`` 代码块时主动清理异常变量 ``exc``，避免形成
            # 引用环。数据库调用接收的是稍后执行的 lambda，因此不能让 lambda 直接
            # 捕获 ``exc``；先复制成普通局部变量，才能保证延迟执行时值仍然存在。
            error_code = exc.code
            safe_message = exc.safe_message
            await context.events.run_error(error_code, safe_message)
            await context.call_database(
                name="database.run.finish",
                operation=lambda: self._database.finish_run(
                    request.run_id,
                    RunStatus.FAILED,
                    error_code,
                ),
                input_data={
                    "run_id": request.run_id,
                    "status": RunStatus.FAILED,
                    "error_code": error_code,
                },
            )
            raise
        except Exception:
            # 未知异常不把内部消息返回用户；API 层会记录堆栈，本层只保证租约释放和
            # Run 终态。错误事件使用固定文案，避免原始异常包含 SQL、URL 或凭据。
            await context.events.run_error("INTERNAL_ERROR", "系统暂时无法处理，请稍后重试")
            await context.call_database(
                name="database.run.finish",
                operation=lambda: self._database.finish_run(
                    request.run_id,
                    RunStatus.FAILED,
                    "INTERNAL_ERROR",
                ),
                input_data={
                    "run_id": request.run_id,
                    "status": RunStatus.FAILED,
                    "error_code": "INTERNAL_ERROR",
                },
            )
            raise

    async def _dispatch_with_deadline(
        self,
        *,
        user_id: str,
        request: RunAgentInput,
        admission: RunAdmission,
        context: ExecutionContext,
    ) -> GraphExecutionResult | None:
        """给一次业务分发施加真正的 Run 总截止时间。

        每个 Delegate 自己还有 15 秒单次上限，但一次 Graph 可能串行调用多个 Delegate，
        也可能卡在数据库或框架代码中。只在调用前检查剩余时间不能保证总计不超过
        100 秒，因此这里用 ``asyncio.timeout`` 覆盖完整业务分发。Run/场景失败收尾和
        Trace 刷新位于超时边界之外，仍有机会释放租约，不能被总截止时间一起取消。
        """

        context.deadline.ensure_remaining()
        try:
            async with asyncio.timeout(context.deadline.remaining_seconds):
                return await self._dispatch(
                    user_id=user_id,
                    request=request,
                    admission=admission,
                    context=context,
                )
        except TimeoutError as exc:
            # asyncio.timeout 在边界外把内部取消转换成 TimeoutError。业务层只暴露稳定
            # 领域错误，不能让 API 根据 Python 内置异常猜测错误码。
            raise RunDeadlineExceededError("本次处理时间已超过系统上限，请重试") from exc

    async def _dispatch(
        self,
        *,
        user_id: str,
        request: RunAgentInput,
        admission: RunAdmission,
        context: ExecutionContext,
    ) -> GraphExecutionResult | None:
        """按输入种类分发到按钮、ReAct、切换确认或 Graph 恢复。"""

        active = await context.call_database(
            name="database.scenario.get_active",
            operation=lambda: self._database.get_active_scenario(
                user_id,
                request.thread_id,
            ),
            input_data={"user_id": user_id, "thread_id": request.thread_id},
        )
        procurement_input = request.forwarded_props.procurement_input

        if isinstance(procurement_input, ScenarioTriggerInput):
            if active is not None and not active.status.is_terminal:
                raise InvalidUserInputError("当前场景尚未结束，不能再次点击场景入口")
            return await self._runner.start(
                scenario_id=procurement_input.scenario_id,
                input_source=InputSource.BUTTON,
                original_user_text=None,
                context=context,
            )

        if procurement_input is None:
            original_text = request.original_user_text
            assert original_text is not None
            user_message = MessageRecord(
                message_id=request.messages[-1].id,
                thread_id=request.thread_id,
                user_id=user_id,
                run_id=request.run_id,
                role="user",
                content=original_text,
                created_at=self._clock.now(),
            )
            await context.call_database(
                name="database.message.append",
                operation=lambda: self._database.append_message(user_message),
                input_data=user_message,
            )
            memory = await context.call_database(
                name="database.memory.load",
                operation=lambda: self._database.load_memory(user_id),
                input_data={"user_id": user_id},
            )
            if active is not None and not active.status.is_terminal:
                await self._scene_switch.propose(
                    active_scenario=active,
                    original_user_text=original_text,
                    memory=memory,
                    context=context,
                )
                return None

            route = await self._router.route(
                original_user_text=original_text,
                memory=memory,
                context=context,
            )
            if route.scenario_id is None:
                await context.events.text_message(
                    route.clarification or "请说明你需要购买商品还是查询采购知识。"
                )
                return None
            return await self._runner.start(
                scenario_id=route.scenario_id,
                input_source=InputSource.NATURAL_LANGUAGE,
                original_user_text=original_text,
                context=context,
            )

        if not isinstance(procurement_input, (ActionInput, FormSubmitInput)):
            raise InvalidUserInputError("不支持的采购输入类型")
        if admission.consumed_action is None:
            raise InvalidUserInputError("本次请求没有有效 Action")
        if active is None or active.status.is_terminal:
            raise InvalidUserInputError("当前场景已经结束或过期")
        if admission.consumed_action.scenario_instance_id != active.scenario_instance_id:
            raise InvalidUserInputError("Action 不属于当前活动场景")

        operation = ActionOperation(admission.consumed_action.kind)
        if operation in {
            ActionOperation.CONFIRM_SCENE_SWITCH,
            ActionOperation.CANCEL_SCENE_SWITCH,
        }:
            return await self._scene_switch.handle(
                active_scenario=active,
                operation=operation,
                action_payload=admission.consumed_action.payload,
                context=context,
            )

        submitted_values = (
            procurement_input.values
            if isinstance(procurement_input, FormSubmitInput)
            else procurement_input.data
        )
        return await self._runner.resume(
            scenario=active,
            action=admission.consumed_action,
            submitted_values=submitted_values,
            context=context,
        )

    async def _persist_display_output(
        self,
        *,
        user_id: str,
        request: RunAgentInput,
        context: ExecutionContext,
        first_event_index: int,
    ) -> tuple[str, ...]:
        """保存本次新增的助手文字和采购 UI 块，供刷新快照使用。"""

        assistant_texts: list[str] = []
        for event in context.events.events[first_event_index:]:
            if isinstance(event, TextMessageContentEvent):
                assistant_texts.append(event.delta)
                assistant_message = MessageRecord(
                    message_id=self._ids.new("message"),
                    thread_id=request.thread_id,
                    user_id=user_id,
                    run_id=request.run_id,
                    role="assistant",
                    content=event.delta,
                    created_at=self._clock.now(),
                )
                await context.call_database(
                    name="database.message.append",
                    # partial 会在此处固定当前循环值；若使用普通闭包，稍后执行时可能读到
                    # 下一轮变量，Ruff 也会把这种潜在的异步晚绑定判定为风险。
                    operation=partial(self._database.append_message, assistant_message),
                    input_data=assistant_message,
                )
            elif isinstance(event, ProcurementCustomEvent):
                block = event.model_dump(mode="json", by_alias=True)
                await context.call_database(
                    name="database.ui_block.append",
                    operation=partial(
                        self._database.append_ui_block,
                        user_id,
                        request.thread_id,
                        block,
                    ),
                    input_data=block,
                )
        return tuple(assistant_texts)
