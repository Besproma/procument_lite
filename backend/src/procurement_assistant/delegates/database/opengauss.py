"""基于 Psycopg 3 连接池的 OpenGauss Database Delegate。

本模块只使用参数绑定 SQL。目标 OpenGauss 版本、JSONB 适配和 LangGraph 官方
PostgreSQL Checkpointer 兼容性仍必须在真实环境验证；代码存在不等于生产验收通过。
"""

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from psycopg import errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from procurement_assistant.delegates.database.connection_types import OpenGaussPool
from procurement_assistant.delegates.database.interface import (
    ActionRecord,
    AdmissionStatus,
    BeginRunRequest,
    DatabaseDelegate,
    MessageRecord,
    RunAdmission,
    RunRecord,
    ScenarioRecord,
    ThreadRecord,
)
from procurement_assistant.domain.errors import ActionExpiredError, ResourceNotFoundError
from procurement_assistant.domain.lifecycle import ActionStatus, RunStatus, ScenarioStatus
from procurement_assistant.orchestration.actions import WaitRequest, actions_from_wait_request
from procurement_assistant.shared.clock import Clock


def _json_object(value: Any) -> dict[str, Any]:
    """兼容驱动返回 dict 或 JSON 文本的情况，并强制结果必须是对象。"""

    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("数据库 JSON 字段不是对象")
    return dict(decoded)


class OpenGaussDatabaseDelegate(DatabaseDelegate):
    """会话、Run、Action、消息和记忆的 OpenGauss 实现。

    每个公开方法只持有完成本次读写所需的短连接/事务。任何方法都不会把连接返回给
    Graph，也不会在模型、外围 HTTP、SSE 或用户等待期间保持事务。
    """

    def __init__(self, *, pool: OpenGaussPool, clock: Clock) -> None:
        self._pool = pool
        self._clock = clock

    # ---------------------------------------------------------------------
    # 健康检查与 Run 入口事务
    # ---------------------------------------------------------------------

    async def is_ready(self) -> bool:
        """验证连接和主表存在；不在健康检查中调用外围服务或修改 Schema。"""

        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    # 逐表执行只读空结果查询，既能发现迁移遗漏，也不会读取业务内容。
                    # checkpoints 三张表由锁定版本的官方 LangGraph 迁移创建。
                    required_tables = (
                        "assistant_threads",
                        "scenario_instances",
                        "assistant_runs",
                        "thread_execution_leases",
                        "pending_actions",
                        "assistant_messages",
                        "assistant_ui_blocks",
                        "user_memories",
                        "trace_spans",
                        "checkpoints",
                        "checkpoint_blobs",
                        "checkpoint_writes",
                    )
                    for table_name in required_tables:
                        # SQL 标识符不能用普通值参数绑定，因此使用 Psycopg Identifier
                        # 做安全引用；即使未来常量改名也不会形成字符串拼接 SQL。
                        await cursor.execute(
                            sql.SQL("SELECT 1 FROM {} WHERE 1 = 0").format(
                                sql.Identifier(table_name)
                            )
                        )
            return True
        except Exception:
            return False

    async def begin_run(self, request: BeginRunRequest) -> RunAdmission:
        """原子处理幂等、thread 租约、Action 消费和 Run 插入。

        该事务提交后调用方才会运行 Graph。若 Action 校验失败，前面刚取得的租约也会随
        事务整体回滚，不会留下需要人工清理的半成品。
        """

        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor(row_factory=dict_row) as cursor:
                        await cursor.execute(
                            "SELECT * FROM assistant_runs WHERE run_id = %s",
                            (request.run_id,),
                        )
                        existing_row = await cursor.fetchone()
                        if existing_row is not None:
                            existing = self._run_from_row(existing_row)
                            self._assert_owner(
                                existing.user_id,
                                existing.thread_id,
                                request.user_id,
                                request.thread_id,
                            )
                            return RunAdmission(
                                status=AdmissionStatus.DUPLICATE,
                                run=existing,
                            )

                        now = self._clock.now()
                        thread = await self._get_or_create_thread_in_transaction(
                            cursor,
                            request.user_id,
                            request.thread_id,
                            now,
                        )
                        lease_expires_at = now + timedelta(seconds=request.lease_seconds)
                        await cursor.execute(
                            """
                            INSERT INTO thread_execution_leases
                                (thread_id, run_id, expires_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (thread_id) DO UPDATE
                               SET run_id = EXCLUDED.run_id,
                                   expires_at = EXCLUDED.expires_at
                             WHERE thread_execution_leases.expires_at <= %s
                            RETURNING thread_id
                            """,
                            (
                                request.thread_id,
                                request.run_id,
                                lease_expires_at,
                                now,
                            ),
                        )
                        acquired = await cursor.fetchone()
                        if acquired is None:
                            rejected = RunRecord(
                                run_id=request.run_id,
                                thread_id=request.thread_id,
                                user_id=request.user_id,
                                trace_id=request.trace_id,
                                input_type=request.input_type,
                                scenario_instance_id=thread.active_scenario_instance_id,
                                status=RunStatus.REJECTED,
                                started_at=now,
                                finished_at=now,
                                error_code="THREAD_BUSY",
                            )
                            await self._insert_run(cursor, rejected)
                            return RunAdmission(
                                status=AdmissionStatus.THREAD_BUSY,
                                run=rejected,
                            )

                        consumed_action: ActionRecord | None = None
                        if request.action_id is not None:
                            consumed_action = await self._consume_action_in_transaction(
                                cursor,
                                action_id=request.action_id,
                                user_id=request.user_id,
                                thread_id=request.thread_id,
                                run_id=request.run_id,
                                now=now,
                            )

                        run = RunRecord(
                            run_id=request.run_id,
                            thread_id=request.thread_id,
                            user_id=request.user_id,
                            trace_id=request.trace_id,
                            input_type=request.input_type,
                            scenario_instance_id=thread.active_scenario_instance_id,
                            status=RunStatus.RUNNING,
                            started_at=now,
                        )
                        await self._insert_run(cursor, run)
                        return RunAdmission(
                            status=AdmissionStatus.ACCEPTED,
                            run=run,
                            consumed_action=consumed_action,
                        )
        except errors.UniqueViolation:
            # 两个相同 runId 极近到达时都可能在首次 SELECT 看不到对方；唯一约束只让
            # 一个 INSERT 成功。冲突事务回滚后重新读取既有 Run，仍保持幂等语义。
            conflicting_run = await self._load_run(request.run_id)
            if conflicting_run is None:
                raise
            self._assert_owner(
                conflicting_run.user_id,
                conflicting_run.thread_id,
                request.user_id,
                request.thread_id,
            )
            return RunAdmission(status=AdmissionStatus.DUPLICATE, run=conflicting_run)

    async def get_run(
        self,
        run_id: str,
        user_id: str,
        thread_id: str,
    ) -> RunRecord | None:
        """读取已有 Run，确保幂等检查优先于 Action 值预校验。"""

        run = await self._load_run(run_id)
        if run is None:
            return None
        self._assert_owner(run.user_id, run.thread_id, user_id, thread_id)
        return run

    async def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        error_code: str | None = None,
    ) -> None:
        """更新 Run 终态，并且只释放仍属于该 Run 的租约。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        UPDATE assistant_runs
                           SET status = %s, finished_at = %s, error_code = %s
                         WHERE run_id = %s
                        RETURNING thread_id
                        """,
                        (status.value, self._clock.now(), error_code, run_id),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError("Run 不存在")
                    await cursor.execute(
                        """
                        DELETE FROM thread_execution_leases
                         WHERE thread_id = %s AND run_id = %s
                        """,
                        (row["thread_id"], run_id),
                    )

    async def bind_run_to_scenario(self, run_id: str, scenario_instance_id: str) -> None:
        """把创建场景的 Run 与场景实例关联。"""

        async with self._pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE assistant_runs
                       SET scenario_instance_id = %s
                     WHERE run_id = %s
                    """,
                    (scenario_instance_id, run_id),
                )
                if cursor.rowcount != 1:
                    raise ResourceNotFoundError("Run 不存在")

    # ---------------------------------------------------------------------
    # Thread、场景与一次性 Action
    # ---------------------------------------------------------------------

    async def get_or_create_thread(self, user_id: str, thread_id: str) -> ThreadRecord:
        """取得或创建归属于用户的 thread。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    return await self._get_or_create_thread_in_transaction(
                        cursor,
                        user_id,
                        thread_id,
                        self._clock.now(),
                    )

    async def get_thread(self, user_id: str, thread_id: str) -> ThreadRecord | None:
        """只读 thread，不创建空会话。"""

        async with self._pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT * FROM assistant_threads WHERE thread_id = %s",
                    (thread_id,),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        record = ThreadRecord.model_validate(row)
        self._assert_owner(record.user_id, record.thread_id, user_id, thread_id)
        return record

    async def get_action(
        self,
        action_id: str,
        user_id: str,
        thread_id: str,
    ) -> ActionRecord:
        """读取 Action 的 Schema 和状态，供入口在消费前预校验用户值。"""

        async with self._pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT * FROM pending_actions WHERE action_id = %s",
                    (action_id,),
                )
                row = await cursor.fetchone()
        if row is None:
            raise ResourceNotFoundError("操作不存在或不属于当前用户")
        action = self._action_from_row(row)
        self._assert_owner(action.user_id, action.thread_id, user_id, thread_id)
        return action

    async def start_scenario(self, scenario: ScenarioRecord) -> None:
        """创建场景并原子设置 thread 活动指针。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        "SELECT * FROM assistant_threads WHERE thread_id = %s FOR UPDATE",
                        (scenario.thread_id,),
                    )
                    thread_row = await cursor.fetchone()
                    if thread_row is None:
                        raise ResourceNotFoundError("会话不存在")
                    thread = ThreadRecord.model_validate(thread_row)
                    self._assert_owner(
                        thread.user_id,
                        thread.thread_id,
                        scenario.user_id,
                        scenario.thread_id,
                    )
                    if thread.active_scenario_instance_id is not None:
                        await cursor.execute(
                            "SELECT status FROM scenario_instances WHERE scenario_instance_id = %s",
                            (thread.active_scenario_instance_id,),
                        )
                        active_row = await cursor.fetchone()
                        if (
                            active_row is not None
                            and not ScenarioStatus(active_row["status"]).is_terminal
                        ):
                            raise ActionExpiredError("当前会话已经存在活动场景")

                    await cursor.execute(
                        """
                        INSERT INTO scenario_instances (
                            scenario_instance_id, thread_id, user_id, scenario_id,
                            input_source, status, started_at, updated_at, expires_at,
                            current_wait_group_id, ended_at, end_reason
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            scenario.scenario_instance_id,
                            scenario.thread_id,
                            scenario.user_id,
                            scenario.scenario_id,
                            scenario.input_source.value,
                            scenario.status.value,
                            scenario.started_at,
                            scenario.updated_at,
                            scenario.expires_at,
                            scenario.current_wait_group_id,
                            scenario.ended_at,
                            scenario.end_reason,
                        ),
                    )
                    await cursor.execute(
                        """
                        UPDATE assistant_threads
                           SET active_scenario_instance_id = %s, updated_at = %s
                         WHERE thread_id = %s
                        """,
                        (
                            scenario.scenario_instance_id,
                            self._clock.now(),
                            scenario.thread_id,
                        ),
                    )

    async def get_active_scenario(
        self,
        user_id: str,
        thread_id: str,
    ) -> ScenarioRecord | None:
        """读取活动场景，并在同一短事务中惰性处理 24 小时过期。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        "SELECT * FROM assistant_threads WHERE thread_id = %s FOR UPDATE",
                        (thread_id,),
                    )
                    thread_row = await cursor.fetchone()
                    if thread_row is None:
                        return None
                    thread = ThreadRecord.model_validate(thread_row)
                    self._assert_owner(thread.user_id, thread.thread_id, user_id, thread_id)
                    if thread.active_scenario_instance_id is None:
                        return None
                    await cursor.execute(
                        "SELECT * FROM scenario_instances "
                        "WHERE scenario_instance_id = %s FOR UPDATE",
                        (thread.active_scenario_instance_id,),
                    )
                    scenario_row = await cursor.fetchone()
                    if scenario_row is None:
                        raise ResourceNotFoundError("活动场景记录不存在")
                    scenario = ScenarioRecord.model_validate(scenario_row)
                    if not scenario.status.is_terminal and scenario.expires_at <= self._clock.now():
                        await self._set_scenario_status_in_transaction(
                            cursor,
                            scenario,
                            ScenarioStatus.EXPIRED,
                            "checkpoint_expired",
                        )
                        return scenario.model_copy(
                            update={
                                "status": ScenarioStatus.EXPIRED,
                                "updated_at": self._clock.now(),
                                "ended_at": self._clock.now(),
                                "end_reason": "checkpoint_expired",
                                "current_wait_group_id": None,
                            }
                        )
                    if scenario.status.is_terminal:
                        await cursor.execute(
                            """
                            UPDATE assistant_threads
                               SET active_scenario_instance_id = NULL, updated_at = %s
                             WHERE thread_id = %s
                            """,
                            (self._clock.now(), thread_id),
                        )
                        return None
                    return scenario

    async def update_scenario_status(
        self,
        scenario_instance_id: str,
        status: ScenarioStatus,
        reason: str | None = None,
    ) -> None:
        """更新生命周期；终态同时清活动指针并使 Action 失效。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        "SELECT * FROM scenario_instances "
                        "WHERE scenario_instance_id = %s FOR UPDATE",
                        (scenario_instance_id,),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError("场景不存在")
                    await self._set_scenario_status_in_transaction(
                        cursor,
                        ScenarioRecord.model_validate(row),
                        status,
                        reason,
                    )

    async def expire_active_scenarios(self, reason: str) -> int:
        """在发布前原子终止全部活动场景，保留记录但让旧 Action 不可恢复。

        发布脚本会先停止接收新请求，再调用本方法。即便有一个遗留请求同时结束，行锁
        也能让两边按提交顺序完成；这里不删除 Checkpoint 或历史数据，用户刷新时能看到
        已过期状态，且不会把旧 Graph 状态误套到新代码上。
        """

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT scenario_instance_id, thread_id
                          FROM scenario_instances
                         WHERE status IN (%s, %s)
                         FOR UPDATE
                        """,
                        (ScenarioStatus.RUNNING.value, ScenarioStatus.WAITING.value),
                    )
                    rows = await cursor.fetchall()
                    if not rows:
                        return 0

                    now = self._clock.now()
                    scenario_ids = tuple(row["scenario_instance_id"] for row in rows)
                    await cursor.execute(
                        """
                        UPDATE scenario_instances
                           SET status = %s,
                               updated_at = %s,
                               ended_at = %s,
                               end_reason = %s,
                               current_wait_group_id = NULL
                         WHERE scenario_instance_id = ANY(%s)
                        """,
                        (
                            ScenarioStatus.EXPIRED.value,
                            now,
                            now,
                            reason,
                            list(scenario_ids),
                        ),
                    )
                    await cursor.execute(
                        """
                        UPDATE pending_actions
                           SET status = %s
                         WHERE scenario_instance_id = ANY(%s)
                           AND status = %s
                        """,
                        (
                            ActionStatus.INVALIDATED.value,
                            list(scenario_ids),
                            ActionStatus.PENDING.value,
                        ),
                    )
                    await cursor.execute(
                        """
                        UPDATE assistant_threads
                           SET active_scenario_instance_id = NULL, updated_at = %s
                         WHERE active_scenario_instance_id = ANY(%s)
                        """,
                        (now, list(scenario_ids)),
                    )
                    return len(rows)

    async def save_wait_request(
        self,
        *,
        user_id: str,
        thread_id: str,
        scenario_instance_id: str,
        wait_request: WaitRequest,
    ) -> None:
        """幂等保存 Checkpoint 已生成的一组 Action。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        "SELECT * FROM scenario_instances "
                        "WHERE scenario_instance_id = %s FOR UPDATE",
                        (scenario_instance_id,),
                    )
                    scenario_row = await cursor.fetchone()
                    if scenario_row is None:
                        raise ResourceNotFoundError("场景不存在")
                    scenario = ScenarioRecord.model_validate(scenario_row)
                    self._assert_owner(
                        scenario.user_id,
                        scenario.thread_id,
                        user_id,
                        thread_id,
                    )
                    for definition in actions_from_wait_request(wait_request):
                        await cursor.execute(
                            "SELECT * FROM pending_actions WHERE action_id = %s",
                            (definition.action_id,),
                        )
                        existing_row = await cursor.fetchone()
                        if existing_row is not None:
                            existing = self._action_from_row(existing_row)
                            if (
                                existing.wait_group_id != wait_request.wait_group_id
                                or existing.scenario_instance_id != scenario_instance_id
                            ):
                                raise ValueError("重复 action_id 指向不同等待点")
                            continue
                        await cursor.execute(
                            """
                            INSERT INTO pending_actions (
                                action_id, wait_group_id, thread_id, user_id,
                                scenario_instance_id, kind, input_schema_id, status,
                                payload_json, created_at, expires_at,
                                consumed_at, consumed_by_run_id
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                      %s, %s, %s, %s)
                            """,
                            (
                                definition.action_id,
                                wait_request.wait_group_id,
                                thread_id,
                                user_id,
                                scenario_instance_id,
                                definition.kind.value,
                                definition.input_schema_id,
                                ActionStatus.PENDING.value,
                                Jsonb(definition.payload),
                                wait_request.created_at,
                                wait_request.expires_at,
                                None,
                                None,
                            ),
                        )
                    await cursor.execute(
                        """
                        UPDATE scenario_instances
                           SET current_wait_group_id = %s, updated_at = %s
                         WHERE scenario_instance_id = %s
                        """,
                        (
                            wait_request.wait_group_id,
                            self._clock.now(),
                            scenario_instance_id,
                        ),
                    )

    async def set_current_wait_group(
        self,
        scenario_instance_id: str,
        wait_group_id: str | None,
    ) -> None:
        """恢复场景切换前的有效等待组。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    if wait_group_id is not None:
                        await cursor.execute(
                            """
                            SELECT 1 FROM pending_actions
                             WHERE scenario_instance_id = %s
                               AND wait_group_id = %s
                               AND status = %s
                             LIMIT 1
                            """,
                            (
                                scenario_instance_id,
                                wait_group_id,
                                ActionStatus.PENDING.value,
                            ),
                        )
                        if await cursor.fetchone() is None:
                            raise ActionExpiredError("原等待操作已经失效")
                    await cursor.execute(
                        """
                        UPDATE scenario_instances
                           SET current_wait_group_id = %s, updated_at = %s
                         WHERE scenario_instance_id = %s
                        """,
                        (wait_group_id, self._clock.now(), scenario_instance_id),
                    )
                    if cursor.rowcount != 1:
                        raise ResourceNotFoundError("场景不存在")

    # ---------------------------------------------------------------------
    # 会话展示内容与个人长期记忆
    # ---------------------------------------------------------------------

    async def append_message(self, message: MessageRecord) -> None:
        """持久化原始用户文字或可展示助手文字。"""

        async with self._pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO assistant_messages (
                        message_id, thread_id, user_id, run_id, role, content, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message.message_id,
                        message.thread_id,
                        message.user_id,
                        message.run_id,
                        message.role,
                        message.content,
                        message.created_at,
                    ),
                )

    async def list_messages(
        self,
        user_id: str,
        thread_id: str,
    ) -> tuple[MessageRecord, ...]:
        """按创建时间恢复当前用户 thread 的消息。"""

        await self._require_thread_owner(user_id, thread_id)
        async with self._pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT message_id, thread_id, user_id, run_id, role, content, created_at
                      FROM assistant_messages
                     WHERE user_id = %s AND thread_id = %s
                     ORDER BY created_at, message_id
                    """,
                    (user_id, thread_id),
                )
                rows = await cursor.fetchall()
        return tuple(MessageRecord.model_validate(row) for row in rows)

    async def append_ui_block(
        self,
        user_id: str,
        thread_id: str,
        block: dict[str, Any],
    ) -> None:
        """保存已经通过协议模型校验的采购 UI 块。"""

        await self._require_thread_owner(user_id, thread_id)
        async with self._pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO assistant_ui_blocks
                        (thread_id, user_id, block_json, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (thread_id, user_id, Jsonb(block), self._clock.now()),
                )

    async def list_ui_blocks(
        self,
        user_id: str,
        thread_id: str,
    ) -> tuple[dict[str, Any], ...]:
        """返回持久化 UI 块，快照层再压缩成当前投影。"""

        await self._require_thread_owner(user_id, thread_id)
        async with self._pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT block_json FROM assistant_ui_blocks
                     WHERE user_id = %s AND thread_id = %s
                     ORDER BY block_id
                    """,
                    (user_id, thread_id),
                )
                rows = await cursor.fetchall()
        return tuple(_json_object(row["block_json"]) for row in rows)

    async def load_memory(self, user_id: str) -> dict[str, Any]:
        """读取一个用户的完整个人记忆 JSON。"""

        async with self._pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT memory_json FROM user_memories WHERE user_id = %s",
                    (user_id,),
                )
                row = await cursor.fetchone()
        return {} if row is None else _json_object(row["memory_json"])

    async def merge_memory(
        self,
        user_id: str,
        updates: dict[str, Any],
        remove_keys: tuple[str, ...],
        source_run_id: str,
    ) -> None:
        """锁定最新记忆后合并顶层补丁，避免多 thread 整份互相覆盖。"""

        async with self._pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        "SELECT memory_json FROM user_memories WHERE user_id = %s FOR UPDATE",
                        (user_id,),
                    )
                    row = await cursor.fetchone()
                    latest = {} if row is None else _json_object(row["memory_json"])
                    for key in remove_keys:
                        latest.pop(key, None)
                    latest.update(updates)
                    await cursor.execute(
                        """
                        INSERT INTO user_memories
                            (user_id, memory_json, source_run_id, updated_at, last_error)
                        VALUES (%s, %s, %s, %s, NULL)
                        ON CONFLICT (user_id) DO UPDATE
                           SET memory_json = EXCLUDED.memory_json,
                               source_run_id = EXCLUDED.source_run_id,
                               updated_at = EXCLUDED.updated_at,
                               last_error = NULL
                        """,
                        (
                            user_id,
                            Jsonb(latest),
                            source_run_id,
                            self._clock.now(),
                        ),
                    )

    # ---------------------------------------------------------------------
    # 只供上述公开方法复用的事务内辅助函数
    # ---------------------------------------------------------------------

    async def _load_run(self, run_id: str) -> RunRecord | None:
        """唯一冲突回滚后在新连接中读取 Run。"""

        async with self._pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT * FROM assistant_runs WHERE run_id = %s",
                    (run_id,),
                )
                row = await cursor.fetchone()
        return None if row is None else self._run_from_row(row)

    async def _require_thread_owner(self, user_id: str, thread_id: str) -> ThreadRecord:
        """集中执行 thread 归属校验，错误统一按未找到处理。"""

        thread = await self.get_thread(user_id, thread_id)
        if thread is None:
            raise ResourceNotFoundError("会话不存在或不属于当前用户")
        return thread

    async def _get_or_create_thread_in_transaction(
        self,
        cursor: Any,
        user_id: str,
        thread_id: str,
        now: datetime,
    ) -> ThreadRecord:
        """仅供已有事务调用：创建后锁定并验证 thread。"""

        await cursor.execute(
            """
            INSERT INTO assistant_threads
                (thread_id, user_id, active_scenario_instance_id, created_at, updated_at)
            VALUES (%s, %s, NULL, %s, %s)
            ON CONFLICT (thread_id) DO NOTHING
            """,
            (thread_id, user_id, now, now),
        )
        await cursor.execute(
            "SELECT * FROM assistant_threads WHERE thread_id = %s FOR UPDATE",
            (thread_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ResourceNotFoundError("会话创建失败")
        record = ThreadRecord.model_validate(row)
        self._assert_owner(record.user_id, record.thread_id, user_id, thread_id)
        return record

    async def _insert_run(self, cursor: Any, run: RunRecord) -> None:
        """在调用方事务中插入一条 Run。"""

        await cursor.execute(
            """
            INSERT INTO assistant_runs (
                run_id, thread_id, user_id, trace_id, input_type,
                scenario_instance_id, status, started_at, finished_at, error_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run.run_id,
                run.thread_id,
                run.user_id,
                run.trace_id,
                run.input_type,
                run.scenario_instance_id,
                run.status.value,
                run.started_at,
                run.finished_at,
                run.error_code,
            ),
        )

    async def _consume_action_in_transaction(
        self,
        cursor: Any,
        *,
        action_id: str,
        user_id: str,
        thread_id: str,
        run_id: str,
        now: datetime,
    ) -> ActionRecord:
        """锁定、校验并一次性消费 Action，同时使同组兄弟失效。"""

        await cursor.execute(
            "SELECT * FROM pending_actions WHERE action_id = %s FOR UPDATE",
            (action_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ResourceNotFoundError("操作不存在或不属于当前用户")
        action = self._action_from_row(row)
        self._assert_owner(action.user_id, action.thread_id, user_id, thread_id)
        await cursor.execute(
            """
            SELECT current_wait_group_id, status
              FROM scenario_instances
             WHERE scenario_instance_id = %s
             FOR UPDATE
            """,
            (action.scenario_instance_id,),
        )
        scenario_row = await cursor.fetchone()
        if scenario_row is None:
            raise ActionExpiredError("操作所属场景不存在")
        if scenario_row["current_wait_group_id"] != action.wait_group_id:
            raise ActionExpiredError("操作不属于当前等待步骤")
        if ScenarioStatus(scenario_row["status"]).is_terminal:
            raise ActionExpiredError("场景已经结束")
        if action.status != ActionStatus.PENDING or action.expires_at <= now:
            raise ActionExpiredError("操作已失效，请刷新页面后重试")

        await cursor.execute(
            """
            UPDATE pending_actions
               SET status = %s, consumed_at = %s, consumed_by_run_id = %s
             WHERE action_id = %s
            """,
            (ActionStatus.CONSUMED.value, now, run_id, action_id),
        )
        await cursor.execute(
            """
            UPDATE pending_actions
               SET status = %s
             WHERE wait_group_id = %s
               AND action_id <> %s
               AND status = %s
            """,
            (
                ActionStatus.INVALIDATED.value,
                action.wait_group_id,
                action_id,
                ActionStatus.PENDING.value,
            ),
        )
        return action.model_copy(
            update={
                "status": ActionStatus.CONSUMED,
                "consumed_at": now,
                "consumed_by_run_id": run_id,
            }
        )

    async def _set_scenario_status_in_transaction(
        self,
        cursor: Any,
        scenario: ScenarioRecord,
        status: ScenarioStatus,
        reason: str | None,
    ) -> None:
        """在调用方事务中完成场景状态及其关联资源更新。"""

        now = self._clock.now()
        await cursor.execute(
            """
            UPDATE scenario_instances
               SET status = %s,
                   updated_at = %s,
                   current_wait_group_id = %s,
                   ended_at = %s,
                   end_reason = %s
             WHERE scenario_instance_id = %s
            """,
            (
                status.value,
                now,
                None if status.is_terminal else scenario.current_wait_group_id,
                now if status.is_terminal else None,
                reason,
                scenario.scenario_instance_id,
            ),
        )
        if status.is_terminal:
            await cursor.execute(
                """
                UPDATE pending_actions
                   SET status = %s
                 WHERE scenario_instance_id = %s AND status = %s
                """,
                (
                    ActionStatus.INVALIDATED.value,
                    scenario.scenario_instance_id,
                    ActionStatus.PENDING.value,
                ),
            )
            await cursor.execute(
                """
                UPDATE assistant_threads
                   SET active_scenario_instance_id = NULL, updated_at = %s
                 WHERE thread_id = %s AND active_scenario_instance_id = %s
                """,
                (now, scenario.thread_id, scenario.scenario_instance_id),
            )

    @staticmethod
    def _run_from_row(row: Mapping[str, Any]) -> RunRecord:
        return RunRecord.model_validate(row)

    @staticmethod
    def _action_from_row(row: Mapping[str, Any]) -> ActionRecord:
        values = dict(row)
        values["payload"] = _json_object(values.pop("payload_json"))
        return ActionRecord.model_validate(values)

    @staticmethod
    def _assert_owner(
        actual_user_id: str,
        actual_thread_id: str,
        requested_user_id: str,
        requested_thread_id: str,
    ) -> None:
        """归属不一致与不存在使用相同错误，防止枚举其他用户资源。"""

        if actual_user_id != requested_user_id or actual_thread_id != requested_thread_id:
            raise ResourceNotFoundError("资源不存在或不属于当前用户")
