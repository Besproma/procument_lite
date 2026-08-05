"""会话快照查询端点。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from procurement_assistant.core.api.dependencies import get_user_id
from procurement_assistant.core.api.runtime import APIRuntime
from procurement_assistant.core.domain.errors import ResourceNotFoundError
from procurement_assistant.core.protocol.snapshot import (
    SessionSnapshot,
    SnapshotBlockPolicy,
    SnapshotMessage,
)


def _compact_ui_blocks(
    blocks: tuple[dict[str, Any], ...],
    *,
    include_interactive: bool,
    policy: SnapshotBlockPolicy,
) -> tuple[dict[str, Any], ...]:
    """保留恢复当前界面所需的最新 UI 投影。

    数据库保存全部历史块用于审计，但刷新页面时不能重新激活旧 Action。Form、Options
    和 Actions 三类交互块只保留三者中最后签发的一项；其他界面状态按事件名保留最新
    一项。普通助手文字已经从 messages 恢复，不重复依赖 UI 块。
    """

    latest_by_slot: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, block in enumerate(blocks):
        name = block.get("name")
        if isinstance(name, str) and policy.is_interactive(name):
            # UI 历史表只记录曾经展示过的块，并不等同于 Action 当前状态。场景完成、
            # 中止、过期后活动指针会被清空；此时若继续返回旧 Form/按钮，用户一定会
            # 点击到已经失效的 Action。没有活动场景时只恢复消息和非交互展示块。
            if not include_interactive:
                continue
            latest_by_slot["interactive"] = (index, block)
        elif isinstance(name, str) and policy.is_restorable(name):
            latest_by_slot[str(name)] = (index, block)
        # scene 使用 snapshot 顶层的数据库权威状态恢复，不能重放历史 waiting 事件；
        # navigation 是一次性浏览器副作用，刷新后重放会再次跳转；agent_stream 是瞬时
        # 进度。三类事件都不能进入恢复投影。
    return tuple(
        block.copy() for _, block in sorted(latest_by_slot.values(), key=lambda item: item[0])
    )


def build_sessions_router(runtime: APIRuntime) -> APIRouter:
    """创建只依赖已装配 runtime 的会话路由。"""

    router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

    @router.get("/{thread_id}/snapshot", response_model=SessionSnapshot)
    async def get_snapshot(
        thread_id: str,
        user_id: Annotated[str, Depends(get_user_id)],
    ) -> SessionSnapshot:
        thread = await runtime.database.get_thread(user_id, thread_id)
        if thread is None:
            raise ResourceNotFoundError("会话不存在或不属于当前用户")

        # get_active_scenario 会按数据库当前时间惰性处理 24 小时过期，因此必须在生成
        # 快照时读取一次，不能只相信 thread 表中可能尚未清理的活动指针。
        scenario = await runtime.database.get_active_scenario(user_id, thread_id)
        messages = await runtime.database.list_messages(user_id, thread_id)
        blocks = await runtime.database.list_ui_blocks(user_id, thread_id)
        return SessionSnapshot(
            thread_id=thread_id,
            scenario_id=scenario.scenario_id if scenario is not None else None,
            scenario_status=scenario.status if scenario is not None else None,
            messages=tuple(
                SnapshotMessage(
                    message_id=message.message_id,
                    role="user" if message.role == "user" else "assistant",
                    content=message.content,
                    created_at=message.created_at,
                )
                for message in messages
                if message.role in {"user", "assistant"}
            ),
            ui_blocks=_compact_ui_blocks(
                blocks,
                include_interactive=scenario is not None and not scenario.status.is_terminal,
                policy=runtime.snapshot_policy,
            ),
            checkpoint_expires_at=scenario.expires_at if scenario is not None else None,
        )

    return router
