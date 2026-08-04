# 部署文件说明

这里提供虚拟机原生部署和 Docker Compose 的最小骨架。服务部署在公司内网，OpenGauss、
模型和外围 Agent 都是外部边界依赖，不在 Compose 中创建假数据库或假接口。

## 发布顺序

1. 在可联网的构建环境解析并提交 `backend/uv.lock` 和 `frontend/package-lock.json`。
2. 执行数据库迁移，并确认 Checkpoint 官方迁移与目标 OpenGauss 版本兼容。
3. 停止接收新请求后执行：

   ```bash
   ./scripts/expire_scenarios.sh deployment
   ```

   命令通过 Database Delegate 将活动场景标记为 `expired`，保留历史和 Checkpoint。
4. 构建并切换后端/前端发布目录，完成 `/health/live`、`/health/ready` 和 SSE 冒烟。
5. 发生程序回滚时，不恢复已经被部署命令标记为过期的旧场景；用户从新版本重新开始。

## 当前环境限制

本工作区当前没有真实 OpenGauss、外围正式协议和可用 npm registry，因此不能在本地
声称生产镜像或生产接入已经验证。Dockerfile 在 `REQUIRE_LOCK=1`（默认）时会主动拒绝
缺少锁文件的构建；这是安全保护，不是静默降级。
