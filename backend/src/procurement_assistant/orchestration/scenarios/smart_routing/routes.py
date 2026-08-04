"""智能分流 Graph 的纯条件路由。

路由函数只读取结构化 State，不解析用户文字或外围展示文案。每个返回值都在 ``graph.py``
显式映射到节点，因此业务分支可以被代码评审和集成测试完整枚举。
"""

from procurement_assistant.orchestration.actions import ActionOperation
from procurement_assistant.orchestration.scenarios.smart_routing.state import SmartRoutingState


def after_prepare_missing_fields(state: SmartRoutingState) -> str:
    """字段仍缺失则等待，否则进入 IOI。"""

    return "wait" if state.wait_request is not None else "ready"


def after_ioi(state: SmartRoutingState) -> str:
    """IOI 为真直接跳转；只有明确 false 才识别栏目。"""

    if state.is_ioi is True:
        return "ioi"
    if state.is_ioi is False:
        return "non_ioi"
    raise RuntimeError("IOI 路由缺少判断结果")


def after_column_recognition(state: SmartRoutingState) -> str:
    """按候选数量决定热线、直接选择或单次用户选择。"""

    count = len(state.column_candidates)
    if count == 0:
        return "empty"
    if count == 1:
        return "single"
    return "multiple"


def after_present_recommendation(state: SmartRoutingState) -> str:
    """搜索为空直接进入采购方式，有商品则等待用户操作。"""

    if state.recommendation is None:
        raise RuntimeError("推荐展示路由缺少 RecommendationState")
    return "has_products" if state.recommendation.products else "empty"


def recommendation_action(state: SmartRoutingState) -> str:
    """把用户已选择的推荐 Action 映射为固定节点。"""

    routes = {
        ActionOperation.NEXT_PAGE: "next_page",
        ActionOperation.APPEND_PRODUCT: "append_product",
        ActionOperation.OTHER_PROCUREMENT_MODE: "other_mode",
        ActionOperation.END_RECOMMENDATION: "end",
    }
    selected_action = state.selected_action
    if selected_action is None:
        raise RuntimeError("推荐 Action 路由缺少用户选择")
    try:
        return routes[selected_action]
    except KeyError as exc:
        raise RuntimeError("推荐 Action 路由收到未知操作") from exc


def procurement_mode(state: SmartRoutingState) -> str:
    """栏目允许自采才调用重复探针，否则直接自定义采购。"""

    if state.selected_column is None:
        raise RuntimeError("采购方式路由缺少选中栏目")
    return "check_duplicate" if state.selected_column.self_purchase_allowed else "custom"


def after_duplicate_check(state: SmartRoutingState) -> str:
    """重复自采业务不允许再次自采，因此进入自定义采购。"""

    if state.duplicate_self_purchase is True:
        return "custom"
    if state.duplicate_self_purchase is False:
        return "self_purchase"
    raise RuntimeError("重复自采路由缺少判断结果")
