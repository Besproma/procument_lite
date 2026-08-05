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

from procurement_assistant.core.api.agent import build_agent_router
from procurement_assistant.core.api.errors import error_response
from procurement_assistant.core.api.health import build_health_router
from procurement_assistant.core.api.runtime import APIRuntime
from procurement_assistant.core.api.sessions import build_sessions_router
from procurement_assistant.core.domain.errors import ProcurementAssistantError
from procurement_assistant.core.protocol.snapshot import ErrorResponse

_LOGGER = logging.getLogger(__name__)


def create_app(runtime: APIRuntime) -> FastAPI:
    """使用已经装配好的运行时对象创建 FastAPI 应用。

    本函数主要负责 HTTP 世界的公共规则：启动/关闭资源、中间件、异常转换、跨域和
    Router 注册。采购流程如何判断不放在这里。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """管理整个服务从启动到关闭的资源生命周期。

        ``yield`` 之前只执行一次启动操作；服务运行期间停在 yield；进程准备关闭时再
        执行 yield 后面的 finally，关闭数据库连接池、HTTP 客户端和后台任务。
        """

        del app
        await runtime.start_resources()
        try:
            yield
        finally:
            await runtime.background_tasks.close(
                timeout_seconds=runtime.settings.memory_shutdown_timeout_seconds
            )
            await runtime.close_resources()

    # 这里才真正创建 FastAPI 应用。runtime 放进 app.state 后，中间件等公共组件也能
    # 取得同一套运行时对象；业务 Router 仍通过函数参数显式接收 runtime。
    app = FastAPI(title=runtime.settings.app_name, lifespan=lifespan)
    app.state.runtime = runtime

    @app.middleware("http")
    async def assign_trace_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """给每个 HTTP 请求先分配一个调用链编号，再交给具体接口。

        中间件像进入办公楼前的门卫：所有请求都会先经过这里。``call_next`` 才表示继续
        交给后面的请求校验和 Router，因此即使 JSON 校验失败也已经有 trace_id 可查询。
        """

        request.state.trace_id = runtime.ids.new("trace")
        response = await call_next(request)
        # 同一个编号也放在响应头里，前端报错时可以把它提供给排障人员。
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

    # include_router 相当于把不同功能的“接口清单”安装到 FastAPI 应用。
    # 主处理接口 POST /api/v1/agent 就在 build_agent_router 中注册。
    app.include_router(build_agent_router(runtime))
    # 会话快照和健康检查使用独立 Router，避免主入口文件越来越大。
    app.include_router(build_sessions_router(runtime))
    app.include_router(build_health_router(runtime))
    return app
