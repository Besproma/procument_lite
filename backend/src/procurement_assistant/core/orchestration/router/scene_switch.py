"""活动 Graph 执行期间的场景切换确认。"""

from procurement_assistant.core.delegates.database.interface import DatabaseDelegate, ScenarioRecord
from procurement_assistant.core.domain.errors import InvalidUserInputError
from procurement_assistant.core.domain.lifecycle import InputSource, ScenarioStatus
from procurement_assistant.core.orchestration.actions import (
    CANCEL_SCENE_SWITCH_OPERATION,
    CONFIRM_SCENE_SWITCH_OPERATION,
)
from procurement_assistant.core.orchestration.graph_runner import GraphExecutionResult, GraphRunner
from procurement_assistant.core.orchestration.router.react_router import ReactScenarioRouter
from procurement_assistant.core.orchestration.runtime import ExecutionContext
from procurement_assistant.core.orchestration.wait_factory import CoreWaitRequestFactory
from procurement_assistant.core.protocol.events import CoreEventName, ScenePayload


class SceneSwitchCoordinator:
    """把“想换场景”转换为用户明确确认，而不是立即中止 Graph。"""

    def __init__(
        self,
        *,
        database: DatabaseDelegate,
        router: ReactScenarioRouter,
        runner: GraphRunner,
        waits: CoreWaitRequestFactory,
        empty_action_schema_id: str,
    ) -> None:
        self._database = database
        self._router = router
        self._runner = runner
        self._waits = waits
        self._empty_action_schema_id = empty_action_schema_id

    async def propose(
        self,
        *,
        active_scenario: ScenarioRecord,
        original_user_text: str,
        memory: dict[str, object],
        context: ExecutionContext,
    ) -> None:
        """识别新意图；目标不同时签发确认/取消 Action。"""

        route = await self._router.route(
            original_user_text=original_user_text,
            memory=memory,
            context=context,
        )
        if route.scenario_id is None:
            await context.events.text_message(
                route.clarification or "请说明是否要切换到其他采购场景。"
            )
            return
        if route.scenario_id == active_scenario.scenario_id:
            await context.events.text_message(
                "当前场景仍在进行中，请使用页面上的表单或操作按钮继续。"
            )
            return

        wait_request = self._waits.scene_switch(
            target_scenario_id=route.scenario_id,
            previous_wait_group_id=active_scenario.current_wait_group_id,
            original_user_text=original_user_text,
            empty_schema_id=self._empty_action_schema_id,
        )
        await context.call_database(
            name="database.wait_request.save_scene_switch",
            operation=lambda: self._database.save_wait_request(
                user_id=context.user_id,
                thread_id=context.thread_id,
                scenario_instance_id=active_scenario.scenario_instance_id,
                wait_request=wait_request,
            ),
            input_data=wait_request,
        )
        await self._runner.publish_wait_request(wait_request, context)

    async def handle(
        self,
        *,
        active_scenario: ScenarioRecord,
        operation: str,
        action_payload: dict[str, object],
        context: ExecutionContext,
    ) -> GraphExecutionResult | None:
        """处理切换确认或取消。

        取消只恢复原等待组；确认先把旧场景置为 ``aborted`` 并使旧 Action 失效，再启动
        新场景。顺序不能反过来，否则同一 thread 会短暂存在两个活动场景。
        """

        previous_wait_group_id = action_payload.get("previous_wait_group_id")
        if previous_wait_group_id is not None and not isinstance(previous_wait_group_id, str):
            raise InvalidUserInputError("场景切换记录不完整")

        if operation == CANCEL_SCENE_SWITCH_OPERATION:
            await context.call_database(
                name="database.wait_group.restore",
                operation=lambda: self._database.set_current_wait_group(
                    active_scenario.scenario_instance_id,
                    previous_wait_group_id,
                ),
                input_data={
                    "scenario_instance_id": active_scenario.scenario_instance_id,
                    "wait_group_id": previous_wait_group_id,
                },
            )
            await context.events.text_message("已继续当前场景。")
            await context.events.custom(
                CoreEventName.SCENE,
                ScenePayload(
                    scenario_id=active_scenario.scenario_id,
                    status=ScenarioStatus.WAITING,
                ),
            )
            return None

        if operation != CONFIRM_SCENE_SWITCH_OPERATION:
            raise InvalidUserInputError("当前操作不是场景切换确认")

        target_scenario_id = action_payload.get("target_scenario_id")
        original_user_text = action_payload.get("original_user_text")
        if not isinstance(target_scenario_id, str) or not isinstance(original_user_text, str):
            raise InvalidUserInputError("场景切换目标不完整")

        await context.call_database(
            name="database.scenario.abort_for_switch",
            operation=lambda: self._database.update_scenario_status(
                active_scenario.scenario_instance_id,
                ScenarioStatus.ABORTED,
                reason="user_confirmed_scene_switch",
            ),
            input_data={
                "scenario_instance_id": active_scenario.scenario_instance_id,
                "status": ScenarioStatus.ABORTED,
                "reason": "user_confirmed_scene_switch",
            },
        )
        await context.events.custom(
            CoreEventName.SCENE,
            ScenePayload(
                scenario_id=active_scenario.scenario_id,
                status=ScenarioStatus.ABORTED,
                reason="user_confirmed_scene_switch",
            ),
        )
        return await self._runner.start(
            scenario_id=target_scenario_id,
            input_source=InputSource.NATURAL_LANGUAGE,
            original_user_text=original_user_text,
            context=context,
        )
