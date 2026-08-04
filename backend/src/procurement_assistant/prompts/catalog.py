"""模型任务到 Prompt 文件的静态目录。

Prompt 路径由代码常量决定，用户输入和数据库内容永远不能参与路径拼接。应用启动时
统一加载，缺文件或空文件直接阻止生产就绪。
"""

from importlib import resources

from procurement_assistant.delegates.model.interface import ModelTaskId
from procurement_assistant.domain.errors import ConfigurationError

PROMPT_FILES: dict[ModelTaskId, str] = {
    ModelTaskId.SCENARIO_ROUTER: "scenario_router.md",
    ModelTaskId.PURCHASE_FIELD_EXTRACTION: "purchase_field_extraction.md",
    ModelTaskId.PRODUCT_SEARCH_TERMS: "product_search_terms.md",
    ModelTaskId.MEMORY_UPDATE: "memory_update.md",
}


def load_prompt(task_id: ModelTaskId) -> str:
    """加载一个任务唯一的主 Prompt。"""

    filename = PROMPT_FILES[task_id]
    try:
        content = (
            resources.files("procurement_assistant.prompts")
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(f"缺少模型任务 Prompt：{task_id.value}") from exc
    if not content.strip():
        raise ConfigurationError(f"模型任务 Prompt 不能为空：{task_id.value}")
    return content


def load_all_prompts() -> dict[ModelTaskId, str]:
    """启动时一次性加载全部 Prompt，便于 readiness 检查。"""

    return {task_id: load_prompt(task_id) for task_id in PROMPT_FILES}
