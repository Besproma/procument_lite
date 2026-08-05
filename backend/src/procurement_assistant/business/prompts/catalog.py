"""模型任务到 Prompt 文件的静态目录。

Prompt 路径由代码常量决定，用户输入和数据库内容永远不能参与路径拼接。应用启动时
统一加载，缺文件或空文件直接阻止生产就绪。
"""

from importlib import resources

from procurement_assistant.business.registry.model_tasks import BusinessModelTask
from procurement_assistant.core.domain.errors import ConfigurationError

PROMPT_FILES: dict[str, str] = {
    BusinessModelTask.SCENARIO_ROUTER: "scenario_router.md",
    BusinessModelTask.PURCHASE_FIELD_EXTRACTION: "purchase_field_extraction.md",
    BusinessModelTask.PRODUCT_SEARCH_TERMS: "product_search_terms.md",
    BusinessModelTask.MEMORY_UPDATE: "memory_update.md",
}


class BusinessPromptCatalog:
    """启动时一次读取并校验、运行时只查内存的 Prompt 目录。"""

    def __init__(self) -> None:
        self._prompts = {task_id: _load_prompt_file(task_id) for task_id in PROMPT_FILES}

    def get(self, task_id: str) -> str:
        """按任务编号读取 Prompt；未知编号属于启动装配错误。"""

        try:
            return self._prompts[task_id]
        except KeyError as exc:
            raise ConfigurationError(f"模型任务未注册 Prompt：{task_id}") from exc


def _load_prompt_file(task_id: str) -> str:
    """从固定包路径读取一个 Prompt 文件。"""

    filename = PROMPT_FILES[task_id]
    try:
        content = (
            resources.files("procurement_assistant.business.prompts")
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(f"缺少模型任务 Prompt：{task_id}") from exc
    if not content.strip():
        raise ConfigurationError(f"模型任务 Prompt 不能为空：{task_id}")
    return content
