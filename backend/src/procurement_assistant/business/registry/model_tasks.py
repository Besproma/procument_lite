"""采购业务使用的全部模型任务编号。

任务编号属于 Business：Core 只接受普通字符串并负责执行，不会把当前四个任务写死在
引擎中。新增业务模型任务时，在本文件增加一项，并在 Prompt 目录登记对应文件即可。
"""

from enum import StrEnum


class BusinessModelTask(StrEnum):
    """当前采购业务明确注册的模型任务。"""

    SCENARIO_ROUTER = "scenario_router"
    PURCHASE_FIELD_EXTRACTION = "purchase_field_extraction"
    PRODUCT_SEARCH_TERMS = "product_search_terms"
    MEMORY_UPDATE = "memory_update"
