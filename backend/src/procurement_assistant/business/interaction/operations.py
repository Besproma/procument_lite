"""采购业务 Graph 能识别的操作编号。"""

from enum import StrEnum


class BusinessActionOperation(StrEnum):
    """当前 Business 明确支持的表单、选项和按钮操作。"""

    SUBMIT_FORM = "submit_form"
    SELECT_OPTION = "select_option"
    NEXT_PAGE = "next_page"
    APPEND_PRODUCT = "append_product"
    OTHER_PROCUREMENT_MODE = "other_procurement_mode"
    END_RECOMMENDATION = "end_recommendation"
    GO_SELF_PURCHASE = "go_self_purchase"
    GO_CUSTOM_PURCHASE = "go_custom_purchase"
