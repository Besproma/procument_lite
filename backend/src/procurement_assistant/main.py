"""Uvicorn 启动采购助手后端时首先加载的模块。"""

from procurement_assistant.composition import build_production_app

# 启动命令中的 ``procurement_assistant.main:app`` 分成两部分：
# - ``procurement_assistant.main``：导入当前 Python 模块；
# - ``app``：取得下面创建的 FastAPI 应用对象。
#
# build_production_app 会装配数据库、模型、Graph、应用服务和 Router。这里保持只有一行，
# 是为了让程序入口清楚可见；具体对象如何连接统一到 composition.py 阅读。
app = build_production_app()
