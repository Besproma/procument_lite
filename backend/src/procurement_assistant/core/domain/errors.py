"""稳定、可判断的领域错误。

业务代码只根据这些类型决定追问、重试、拒绝或结束。底层 HTTP/数据库异常必须先在
Delegate 边界映射，不能让 Graph 依赖某个供应方或驱动的异常类。
"""


class ProcurementAssistantError(Exception):
    """所有可预期系统错误的基类。"""

    code = "PROCUREMENT_ASSISTANT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.safe_message = message


class InvalidUserInputError(ProcurementAssistantError):
    """用户输入无法通过当前 Action 的结构校验。"""

    code = "INVALID_USER_INPUT"


class ResourceNotFoundError(ProcurementAssistantError):
    """资源不存在或不属于当前用户；对外不区分两种情况。"""

    code = "RESOURCE_NOT_FOUND"


class ActionExpiredError(ProcurementAssistantError):
    """Action 已过期、消费或不再属于当前等待点。"""

    code = "ACTION_EXPIRED"


class ConcurrentRunError(ProcurementAssistantError):
    """同一个 thread 已经有 Run 正在执行。"""

    code = "THREAD_BUSY"


class DuplicateRunError(ProcurementAssistantError):
    """同一个 ``runId`` 已经登记过，禁止再次执行。

    重复 Run 与普通输入错误不同：客户端很可能只是因为网络重试而重复发送。API 层会
    把该错误映射成 HTTP 409，并同时返回既有 Run 状态和会话快照地址，前端据此恢复
    页面，而不是生成一个新 ``runId`` 后盲目重复业务调用。
    """

    code = "DUPLICATE_RUN"

    def __init__(self, run_status: str) -> None:
        super().__init__("该 runId 已经执行过，请恢复当前会话")
        self.run_status = run_status


class ScenarioExpiredError(ProcurementAssistantError):
    """场景超过恢复期或因代码部署被终止。"""

    code = "SCENARIO_EXPIRED"


class DelegateTimeoutError(ProcurementAssistantError):
    """外围能力在单次调用时限内没有完成。"""

    code = "DELEGATE_TIMEOUT"


class DelegateUnavailableError(ProcurementAssistantError):
    """外围能力临时不可用。"""

    code = "DELEGATE_UNAVAILABLE"


class RetryableDelegateError(DelegateUnavailableError):
    """明确允许自动重试一次的外围错误。"""

    code = "RETRYABLE_DELEGATE_ERROR"


class NonRetryableDelegateError(ProcurementAssistantError):
    """业务拒绝、鉴权错误等不得自动重试的外围错误。"""

    code = "NON_RETRYABLE_DELEGATE_ERROR"


class DelegateContractError(ProcurementAssistantError):
    """外围响应不符合已确认协议，不能写入 Graph。"""

    code = "DELEGATE_CONTRACT_ERROR"


class RunDeadlineExceededError(ProcurementAssistantError):
    """整个 Run 已超过总截止时间。"""

    code = "RUN_DEADLINE_EXCEEDED"


class ConfigurationError(ProcurementAssistantError):
    """应用或某个生产 Delegate 缺少必需配置。"""

    code = "CONFIGURATION_ERROR"


class ServiceOverloadedError(ProcurementAssistantError):
    """当前进程已达到配置的 Run 并发上限。"""

    code = "SERVICE_OVERLOADED"
