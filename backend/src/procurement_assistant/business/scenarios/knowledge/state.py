"""知识推荐 Graph State。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from procurement_assistant.core.domain.lifecycle import InputSource, ScenarioStatus
from procurement_assistant.core.orchestration.actions import WaitRequest
from procurement_assistant.core.orchestration.models import RecoverableError


class KnowledgeState(BaseModel):
    """知识精确匹配跨节点保存的数据。

    完整知识全集不写入 Checkpoint；它只存在于 CachedKnowledgeDelegate 的进程内缓存。
    ``matched_value`` 必须是外部 value 原文，任何节点都不能调用模型改写。
    """

    model_config = ConfigDict(extra="forbid")

    scenario_instance_id: str
    status: ScenarioStatus = ScenarioStatus.RUNNING
    input_source: InputSource
    query_text: str | None = None
    match_found: bool | None = None
    matched_value: str | None = None
    cache_source: Literal["fresh", "cached", "stale"] | None = None
    wait_request: WaitRequest | None = None
    recoverable_error: RecoverableError | None = None
