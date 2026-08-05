"""轻量存活和就绪检查。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from procurement_assistant.core.api.runtime import APIRuntime


def build_health_router(runtime: APIRuntime) -> APIRouter:
    """创建健康检查路由。"""

    router = APIRouter(tags=["health"])

    @router.get("/health/live")
    async def live() -> dict[str, str]:
        """只证明事件循环和 FastAPI 进程仍可响应。"""

        return {"status": "live"}

    @router.get("/health/ready")
    async def ready() -> JSONResponse:
        """检查装配与必要依赖，不逐个调用慢外围服务。"""

        is_ready, reason = await runtime.readiness_probe()
        status_code = 200 if is_ready else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if is_ready else "not_ready",
                # reason 只能由 Composition Root 返回固定安全码，禁止放 DSN、URL 或
                # 原始连接异常。
                "reason": reason,
            },
        )

    return router
