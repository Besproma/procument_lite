"""Uvicorn 生产入口。"""

from procurement_assistant.composition import build_production_app

# Uvicorn 使用 ``procurement_assistant.main:app`` 加载应用。所有连接和 Delegate 的创建
# 仍集中在 composition.py；本文件不允许出现业务判断或测试 Fake。
app = build_production_app()
