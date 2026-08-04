"""FastAPI 应用工厂；不包含采购业务节点。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from procurement_assistant.api.agent import build_agent_router
from procurement_assistant.api.errors import error_response
from procurement_assistant.api.health import build_health_router
from procurement_assistant.api.runtime import APIRuntime
from procurement_assistant.api.sessions import build_sessions_router
from procurement_assistant.domain.errors import ProcurementAssistantError
from procurement_assistant.protocol.snapshot import ErrorResponse

_LOGGER = logging.getLogger(__name__)


def create_app(runtime: APIRuntime) -> FastAPI:
    """使用 Composition Root 已创建的对象构造一个无隐藏依赖的应用。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """只管理显式资源关闭，不在 import 阶段打开连接。"""

        del app
        await runtime.start_resources()
        try:
            yield
        finally:
            await runtime.background_tasks.close(
                timeout_seconds=runtime.settings.memory_shutdown_timeout_seconds
            )
            await runtime.close_resources()

    app = FastAPI(title=runtime.settings.app_name, lifespan=lifespan)
    app.state.runtime = runtime

    @app.middleware("http")
    async def assign_trace_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """给验证失败等尚未进入业务路由的请求也分配安全 trace_id。"""

        request.state.trace_id = runtime.ids.new("trace")
        response = await call_next(request)
        response.headers.setdefault("X-Trace-ID", request.state.trace_id)
        return response

    @app.exception_handler(ProcurementAssistantError)
    async def handle_domain_error(
        request: Request,
        error: ProcurementAssistantError,
    ) -> JSONResponse:
        return error_response(error, trace_id=request.state.trace_id)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        # 不把包含用户原文的 Pydantic errors/input 直接回显；详细验证错误只在受控日志
        # 中按需查询，HTTP 契约保持固定且不会泄露其他资源结构。
        _LOGGER.info(
            "请求结构校验失败，trace_id=%s error_count=%s",
            request.state.trace_id,
            len(error.errors()),
        )
        body = ErrorResponse(
            code="INVALID_REQUEST",
            message="请求结构不合法，请检查字段后重试",
            trace_id=request.state.trace_id,
        )
        return JSONResponse(
            status_code=422,
            content=body.model_dump(mode="json", by_alias=True, exclude_none=True),
        )

    @app.exception_handler(Exception)
    async def handle_unknown_error(request: Request, error: Exception) -> JSONResponse:
        _LOGGER.exception(
            "未处理的 HTTP 异常，trace_id=%s",
            request.state.trace_id,
            exc_info=(type(error), error, error.__traceback__),
        )
        body = ErrorResponse(
            code="INTERNAL_ERROR",
            message="系统暂时无法处理，请稍后重试",
            trace_id=request.state.trace_id,
        )
        return JSONResponse(
            status_code=500,
            content=body.model_dump(mode="json", by_alias=True, exclude_none=True),
        )

    if runtime.settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=runtime.settings.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-User-ID"],
            expose_headers=["X-Trace-ID"],
        )

    app.include_router(build_agent_router(runtime))
    app.include_router(build_sessions_router(runtime))
    app.include_router(build_health_router(runtime))
    return app
