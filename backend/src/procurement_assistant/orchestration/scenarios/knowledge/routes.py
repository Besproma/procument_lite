"""知识推荐 Graph 的纯条件路由。"""

from procurement_assistant.orchestration.scenarios.knowledge.state import KnowledgeState


def after_prepare_query(state: KnowledgeState) -> str:
    """没有查询 key 时等待表单，否则直接匹配。"""

    return "wait" if state.wait_request is not None else "match"
