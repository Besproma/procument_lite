# 采购智能助手轻量版

本项目用于以较少的自研基础设施，快速落地采购智能助手业务。

核心技术路线：

- Python 3.12、FastAPI、LangGraph 和 LangChain。
- React、TypeScript、Vite、Ant Design 和 AG-UI。
- OpenGauss 保存 Checkpoint、会话、长期记忆及调用链。
- ReAct 只负责自然语言场景路由，关键采购流程使用确定性 LangGraph DAG。
- 所有外围 Agent、模型、外部服务和数据库访问都通过 Delegate 隔离。

## 当前状态

后端框架、真实 LangGraph 流程、AG-UI/SSE 协议适配、测试 Fake、持久化边界、Trace、
长期记忆和前端 Demo 已实现；当前仍处于“本地 Fake 可验证、真实外围待接入”阶段。代码
必须严格遵循文档规定的目录边界、生产/测试分离、高可读性和充分详细的中文注释要求。

当前后端还已覆盖以下容易出错的运行时边界：

- 整个 Run 的 100 秒可配置总截止时间，而不只是单个外围请求超时。
- `runId` 幂等优先检查，以及 Action 在消费前校验、事务内复查和同组失效。
- 客户端断线、不可重试错误和部署过期时的 Run、场景、租约与 Action 统一收尾。
- 页面刷新只恢复当前有效交互，不重放历史导航、外围流进度或已经失效的按钮。

唯一权威开发文档：

- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

面向 Python/FastAPI/LangGraph 初学者的调用链阅读指南：

- [docs/API_REQUEST_WALKTHROUGH.md](docs/API_REQUEST_WALKTHROUGH.md)

文档覆盖：LangGraph/LangChain 编排、ReAct 场景路由、Scenario Tool/Atomic Tool、智能分流与知识推荐业务规则、商品推荐 Subgraph、Delegate 适配层、AG-UI + SSE、OpenGauss Checkpoint、长期记忆、全链路 Trace、React 前端、部署、测试和严格验收标准。

代码开发和验收均以该文档为唯一依据。

## 本地验证状态

项目明确区分：

1. **本地可运行完成**：使用测试专用 Fake Delegate 跑通真实 LangGraph 后端和 React 前端。
2. **生产接入完成**：真实 OpenGauss、外围 Agent、搜索、知识、排队、页面跳转和申购单能力全部验证通过。

当前在受限环境中已用 Python 3.12 缓存依赖验证后端集成测试；标准可重复安装仍等待
联网生成锁文件。当前没有 OpenGauss 测试环境、外围接口正式协议和完整前端 npm 依赖，
因此不得误报为“生产接入完成”或“前端构建已通过”。

后端静态门禁（不依赖联网）已经通过：

```text
ruff check backend/src test_support tests        -> passed
ruff format --check backend/src test_support tests -> passed
python -m compileall backend/src test_support tests -> passed
cd backend && mypy                         -> passed（97 个生产源码文件）
Python 3.12.13 + FastAPI 0.141.1 + LangGraph 1.2.10 测试 -> 28 passed
```

在可联网环境中，推荐从项目根目录执行：

```bash
# 后端全部门禁（要求已提交 uv.lock）
./scripts/check_backend.sh

# 前端安装、构建、Lint、格式检查和 Chrome E2E
cd frontend
npm ci
npm run build
npm run lint
npm run format:check
npm run test:e2e
```

发布前活动场景必须通过 Delegate 统一过期：

```bash
./scripts/expire_scenarios.sh deployment
```

审核通过后的开发顺序、目录边界和两级完成标准，以 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 为唯一依据。
