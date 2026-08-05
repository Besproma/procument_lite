#!/usr/bin/env bash

# 发布前运行。脚本不接收 SQL，也不直接连接数据库；所有状态、Action 和活动指针的
# 原子变更由 Python Database Delegate 完成。
set -euo pipefail

reason="${1:-deployment}"
cd "$(dirname "$0")/../backend"
exec uv run --no-dev python -m procurement_assistant.business.administration.expire_scenarios \
  --reason "$reason"
