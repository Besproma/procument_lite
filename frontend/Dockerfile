# 前端多阶段镜像：Node 只负责构建，运行时只有 Nginx 静态文件。
# 构建上下文必须是项目根目录：
#   docker build -f frontend/Dockerfile .

FROM node:24-bookworm-slim AS build

WORKDIR /workspace/frontend
# 通配符至少会复制 package.json；联网生成 package-lock.json 后也会自动把锁文件复制
# 进镜像。依赖描述单独成层，可以在业务源码变化时复用 npm ci 的构建缓存。
COPY frontend/package*.json ./
COPY frontend/tsconfig*.json frontend/vite.config.ts ./
COPY frontend/eslint.config.js frontend/.prettierrc.json frontend/index.html ./
COPY frontend/src ./src

ARG REQUIRE_LOCK=1
RUN if [ "$REQUIRE_LOCK" = "1" ] && [ ! -f /workspace/frontend/package-lock.json ]; then \
      echo "缺少 frontend/package-lock.json：生产构建必须使用 npm ci" >&2; \
      exit 1; \
    elif [ -f /workspace/frontend/package-lock.json ]; then \
      npm ci --ignore-scripts --no-audit --no-fund; \
    else \
      echo "警告：仅供本地探测，正在使用未锁定 npm 依赖" >&2; \
      npm install --ignore-scripts --no-audit --no-fund; \
    fi
RUN npm run build

FROM nginx:1.29-alpine AS runtime

COPY --from=build /workspace/frontend/dist /usr/share/nginx/html
COPY deploy/nginx/procurement-assistant.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
