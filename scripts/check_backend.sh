#!/usr/bin/env bash

# 后端交付门禁的单一入口。必须在 backend 目录执行 uv 的 frozen 模式，避免本地隐式
# 解析出与 CI/生产不同的依赖版本。
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$project_root/backend/uv.lock" ]]; then
  echo "缺少 backend/uv.lock；请在可联网构建环境生成并提交锁文件。" >&2
  exit 2
fi

cd "$project_root/backend"
uv sync --frozen
uv run ruff format --check src ../test_support ../tests
uv run ruff check src ../test_support ../tests
uv run mypy
uv run pytest -q
