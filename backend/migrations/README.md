# 数据库迁移说明

`001_assistant_core.sql` 创建采购助手自有业务表，回滚脚本只允许在无正式数据的新环境使用。

LangGraph Checkpoint 表没有在当前未联网、未锁定 `langgraph-checkpoint-postgres` 精确版本的情况下手写。其表结构属于该依赖的持久化协议，必须在依赖版本锁定后，从同版本官方迁移生成并提交为下一份显式 SQL，再在目标 OpenGauss 验证。生产 `/health/ready` 在这些表和兼容性未验证前不得视为通过。
