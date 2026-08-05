# 数据库迁移说明

`001_assistant_core.sql` 创建采购助手自有业务表，回滚脚本只允许在无正式数据的新环境使用。

`uv.lock` 已锁定 `langgraph-checkpoint-postgres`，但当前仍没有目标 OpenGauss 环境，因此
尚未把官方 Checkpointer 表迁移误报为已兼容。接入生产前必须从锁定版本提取官方迁移，
作为下一份显式、可审阅 SQL 提交，并在目标 OpenGauss 验证 `checkpoint`、`blob`、
`pending writes`、暂停恢复和并发行为。应用启动时不得用 `setup()` 静默改表；上述迁移和
兼容性验证完成前，生产 `/health/ready` 不得视为通过。
