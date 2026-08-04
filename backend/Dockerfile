# 生产后端镜像：最终层不包含测试代码和开发依赖。
# 构建上下文必须是项目根目录：
#   docker build -f backend/Dockerfile .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:/usr/local/bin:${PATH}"

WORKDIR /app

# uv 只是安装/同步工具，不参与业务运行。正式发布应由组织镜像或锁定版本提供；
# 这里不把访问凭据写入镜像层。
RUN python -m pip install --no-cache-dir uv

COPY backend/ ./backend/

ARG REQUIRE_LOCK=1
RUN if [ "$REQUIRE_LOCK" = "1" ] && [ ! -f /app/backend/uv.lock ]; then \
      echo "缺少 backend/uv.lock：生产镜像必须使用 frozen 依赖" >&2; \
      exit 1; \
    elif [ -f /app/backend/uv.lock ]; then \
      uv sync --directory /app/backend --frozen --no-dev; \
    else \
      echo "警告：仅供本地探测，正在使用未锁定依赖" >&2; \
      uv pip install --system --directory /app/backend .; \
    fi

# 使用专用非 root 用户运行。应用只需读取源码和写入系统临时目录。
RUN useradd --create-home --uid 10001 assistant \
    && chown -R assistant:assistant /app
USER assistant

EXPOSE 8000

CMD ["uvicorn", "procurement_assistant.main:app", "--host", "0.0.0.0", "--port", "8000"]
