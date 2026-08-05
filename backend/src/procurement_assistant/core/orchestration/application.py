"""HTTP 接入层调用的 Agent 应用服务。"""

import asyncio
from functools import partial

from pydantic import BaseModel, ConfigDict

from procurement_assistant.core.config.settings import CoreSettings
from procurement_assistant.core.delegates.database.interface import (
    AdmissionStatus,
    BeginRunRequest,
    DatabaseDelegate,
    MessageRecord,
    RunAdmission,
)
from procurement_assistant.core.domain.errors import (
    ConcurrentRunError,
    DuplicateRunError,
    InvalidUserInputError,
    ProcurementAssistantError,
    RunDeadlineExceededError,
)
from procurement_assistant.core.domain.lifecycle import InputSource, RunStatus
from procurement_assistant.core.orchestration.action_registry import ActionInputRegistry
from procurement_assistant.core.orchestration.actions import (
    CANCEL_SCENE_SWITCH_OPERATION,
    CONFIRM_SCENE_SWITCH_OPERATION,
)
from procurement_assistant.core.orchestration.graph_runner import GraphExecutionResult, GraphRunner
from procurement_assistant.core.orchestration.router.react_router import ReactScenarioRouter
from procurement_assistant.core.orchestration.router.scene_switch import SceneSwitchCoordinator
from procurement_assistant.core.orchestration.runtime import ExecutionContext
from procurement_assistant.core.protocol.events import (
    ProcurementCustomEvent,
    TextMessageContentEvent,
)
from procurement_assistant.core.protocol.run_input import (
    ActionInput,
    FormSubmitInput,
    RunAgentInput,
    ScenarioTriggerInput,
)
from procurement_assistant.core.shared.clock import Clock
from procurement_assistant.core.shared.ids import IdGenerator


class ApplicationResult(BaseModel):
    """一次已接受 Run 的应用层结果。"""

    model_config = ConfigDict(extra="forbid")

    graph_result: GraphExecutionResult | None = None
    assistant_texts: tuple[str, ...] = ()


class AgentApplication:
    """位于 HTTP 入口和具体业务 Graph 之间的“总调度员”。

    它不判断“是不是 IOI”或“允许哪种采购方式”，只负责：

    - 受理并登记一次 Run；
    - 判断输入来自场景按钮、自然语言、流程按钮还是表单；
    - 启动或恢复对应 Graph；
    - 保存要展示给用户的结果；
    - 保证成功、报错和断线时都把 Run 正确收尾。
    """

    def __init__(
        self,
        *,
        settings: CoreSettings,
        database: DatabaseDelegate,
        action_inputs: ActionInputRegistry,
        router: ReactScenarioRouter,
        runner: GraphRunner,
        scene_switch: SceneSwitchCoordinator,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._settings = settings
        self._database = database
        self._action_inputs = action_inputs
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
        """在开始流式响应前，判断这次请求能不能被正式受理。

        可以把它想成银行取号：先确认号码没用过、当前窗口没在处理同一会话的另一笔
        请求，并核销本次点击的一次性按钮。返回 ACCEPTED 后才进入真正业务处理。
        """

        procurement_input = request.forwarded_props.procurement_input
        action_id = (
            procurement_input.action_id
            if isinstance(procurement_input, (ActionInput, FormSubmitInput))
            else None
        )
        input_type = procurement_input.type if procurement_input is not None else "natural_language"
        # “幂等”在这里的通俗含义是：相同 run_id 无论被网络重发多少次，都只处理一次。
        # 它的优先级高于请求体内容；网络重试即使携带了损坏的旧 payload，也必须返回
        # DUPLICATE，而不能因为再次预校验失败而暴露另一种结果。
        existing_run = await self._database.get_run(
            request.run_id,
            user_id,
            request.thread_id,
        )
        if existing_run is not None:
            raise DuplicateRunError(existing_run.status.value)

        if isinstance(procurement_input, (ActionInput, FormSubmitInput)):
            # Action 是服务端之前签发的“一次性操作凭证”，例如选择栏目或提交表单。
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
            self._action_inputs.validate(
                action.input_schema_id,
                submitted_values,
                action_payload=action.payload,
            )
        # begin_run 在一个很短的数据库事务中完成 Run 登记、会话占用和 Action 消费。
        # await 返回时事务已经结束；后续调用外部 Agent 时不会一直占着这个事务。
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
        """执行一个已经受理的 Run，并负责成功或失败后的统一收尾。"""

        if admission.status != AdmissionStatus.ACCEPTED:
            # ``admit`` 已经把 duplicate/busy 转换成入口错误；到达这里说明 API 绕过
            # 了规定调用顺序，属于开发错误而不是用户输入错误。
            raise RuntimeError("只有已接受的 Run 才能进入应用执行阶段")

        # 先产生 RUN_STARTED 事件。它会经过 agent.py 的队列和 SSE 到达前端。
        await context.events.run_started()
        # 发射器还保留本次已经产生的事件。记住开始位置，后面只持久化本轮新增内容。
        initial_event_count = len(context.events.events)
        try:
            # _dispatch_with_deadline 根据输入种类选择 Graph，并限制整次业务处理总时长。
            graph_result = await self._dispatch_with_deadline(
                user_id=user_id,
                request=request,
                admission=admission,
                context=context,
            )
            # Graph 产生的事件已经可以通过 SSE 展示；这里再把文字和 UI 块保存到数据库，
            # 用户刷新页面时就能通过会话快照恢复，而不是只能看当前网络连接中的内容。
            assistant_texts = await self._persist_display_output(
                user_id=user_id,
                request=request,
                context=context,
                first_event_index=initial_event_count,
            )
            # 将 Run 标为成功，同时释放数据库里的 thread 占用。
            await context.call_database(
                name="database.run.finish",
                operation=lambda: self._database.finish_run(
                    request.run_id,
                    RunStatus.SUCCEEDED,
                ),
                input_data={"run_id": request.run_id, "status": RunStatus.SUCCEEDED},
            )
            # RUN_FINISHED 是前端判断“本轮处理结束”的信号，必须是成功 Run 的最后一条
            # 事件。先完成必要持久化和租约释放，
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
        """给完整业务处理套上一个可配置的总倒计时。

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
        """识别本次输入类型，并把它送到正确处理路径。

        本方法只有三条主路：

        1. 场景入口按钮：直接启动指定场景；
        2. 自然语言：由 ReAct 路由判断场景后启动；
        3. 流程中的按钮或表单：恢复当前暂停的场景。
        """

        # 先查询当前 thread 是否有尚未结束的场景。场景可能处于 RUNNING，也可能正在
        # WAITING（例如等待用户选择栏目），这个信息决定本次输入是启动还是恢复。
        active = await context.call_database(
            name="database.scenario.get_active",
            operation=lambda: self._database.get_active_scenario(
                user_id,
                request.thread_id,
            ),
            input_data={"user_id": user_id, "thread_id": request.thread_id},
        )
        procurement_input = request.forwarded_props.procurement_input

        # 第一条路：用户点击页面最外层的“智能分流”或“知识推荐”入口按钮。
        # 按钮已经给出了准确 scenario_id，不需要再调用模型猜测意图。
        if isinstance(procurement_input, ScenarioTriggerInput):
            if active is not None and not active.status.is_terminal:
                raise InvalidUserInputError("当前场景尚未结束，不能再次点击场景入口")
            return await self._runner.start(
                scenario_id=procurement_input.scenario_id,
                input_source=InputSource.BUTTON,
                original_user_text=None,
                context=context,
            )

        # 第二条路：procurement_input 为空表示这是一条自然语言消息。
        if procurement_input is None:
            original_text = request.original_user_text
            assert original_text is not None
            # 先把用户原文保存下来。后端会话历史以数据库为准，不信任前端回传的旧消息。
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
            # 长期记忆只辅助非关键的个性化表达和路由，不能替代采购规则判断。
            memory = await context.call_database(
                name="database.memory.load",
                operation=lambda: self._database.load_memory(user_id),
                input_data={"user_id": user_id},
            )
            if active is not None and not active.status.is_terminal:
                # 已在某个场景中时，新文字不能偷偷启动另一个场景。先让场景切换协调器
                # 判断是否需要向用户发出“是否切换”的确认按钮。
                await self._scene_switch.propose(
                    active_scenario=active,
                    original_user_text=original_text,
                    memory=memory,
                    context=context,
                )
                return None

            # 当前没有活动场景，才调用 ReAct 路由选择智能分流或知识推荐。
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

        # 第三条路：用户点击了 Graph 之前签发的按钮，或提交了 Graph 要求的表单。
        if not isinstance(procurement_input, (ActionInput, FormSubmitInput)):
            raise InvalidUserInputError("不支持的采购输入类型")
        if admission.consumed_action is None:
            raise InvalidUserInputError("本次请求没有有效 Action")
        if active is None or active.status.is_terminal:
            raise InvalidUserInputError("当前场景已经结束或过期")
        if admission.consumed_action.scenario_instance_id != active.scenario_instance_id:
            raise InvalidUserInputError("Action 不属于当前活动场景")

        operation = admission.consumed_action.kind
        if operation in {
            CONFIRM_SCENE_SWITCH_OPERATION,
            CANCEL_SCENE_SWITCH_OPERATION,
        }:
            # 场景切换确认属于应用层协调动作，不进入采购业务 Graph。
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
        # 普通按钮/表单是对某个 LangGraph interrupt（暂停点）的回答，从数据库保存的
        # Checkpoint 继续执行，而不是从 Graph 开头重跑。
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
        """保存本次新增的助手文字和采购 UI 块，供刷新页面时恢复。

        SSE 负责“马上给用户看”，数据库负责“刷新后还能看”。两条路径使用的是同一批
        已校验事件，避免前端即时内容和恢复内容来自两套业务逻辑。
        """

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
