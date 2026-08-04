"""入口错误到安全 HTTP JSON 的集中映射。"""

from fastapi.responses import JSONResponse

from procurement_assistant.domain.errors import (
    ActionExpiredError,
    ConcurrentRunError,
    ConfigurationError,
    DelegateTimeoutError,
    DelegateUnavailableError,
    DuplicateRunError,
    InvalidUserInputError,
    ProcurementAssistantError,
    ResourceNotFoundError,
    ScenarioExpiredError,
    ServiceOverloadedError,
)
from procurement_assistant.protocol.snapshot import ErrorResponse


def domain_error_status(error: ProcurementAssistantError) -> int:
    """返回稳定 HTTP 状态，禁止各路由自行决定同类错误的状态码。"""

    if isinstance(error, ResourceNotFoundError):
        return 404
    if isinstance(
        error,
        (DuplicateRunError, ConcurrentRunError, ActionExpiredError, ScenarioExpiredError),
    ):
        return 409
    if isinstance(error, InvalidUserInputError):
        return 400
    if isinstance(error, DelegateTimeoutError):
        return 504
    if isinstance(
        error,
        (ConfigurationError, DelegateUnavailableError, ServiceOverloadedError),
    ):
        return 503
    return 500


def error_response(
    error: ProcurementAssistantError,
    *,
    trace_id: str,
    thread_id: str | None = None,
) -> JSONResponse:
    """构造不包含堆栈、数据库键或供应方响应正文的错误。"""

    snapshot_url: str | None = None
    details: dict[str, str] = {}
    if isinstance(error, DuplicateRunError) and thread_id is not None:
        snapshot_url = f"/api/v1/sessions/{thread_id}/snapshot"
        details["runStatus"] = error.run_status
    body = ErrorResponse(
        code=error.code,
        message=error.safe_message,
        trace_id=trace_id,
        snapshot_url=snapshot_url,
        details=details,
    )
    headers = {"Retry-After": "1"} if isinstance(error, ServiceOverloadedError) else None
    return JSONResponse(
        status_code=domain_error_status(error),
        content=body.model_dump(mode="json", by_alias=True, exclude_none=True),
        headers=headers,
    )
