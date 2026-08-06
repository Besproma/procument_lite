# 采购智能助手数据库交付物

本目录提供数据库设计的两个可审阅交付物：

- [procurement_assistant_data_dictionary.xlsx](procurement_assistant_data_dictionary.xlsx)：面向开发、架构和运维人员的字段字典。它说明每张表的用途、每个字段的含义、数据类型、是否必填、默认值、逻辑关联、索引/约束和敏感性。
- [procurement_assistant_schema.sql](procurement_assistant_schema.sql)：将两份迁移按正确顺序合并后的完整建表参考 DDL。
- [procurement_assistant_class_diagram.html](procurement_assistant_class_diagram.html)：可直接在浏览器打开的数据库/领域类图，展示 13 张表对应的类、关键字段、逻辑关联和 LangGraph Checkpoint 边界。

## 表的范围

当前设计包含 13 张表：

- 9 张助手业务表：会话、场景实例、Run 审计、会话租约、待处理操作、消息、结构化 UI 块、个人长期记忆、调用链 Span。
- 4 张 LangGraph Checkpoint 表：迁移版本、检查点、channel 二进制值、pending writes。

业务表的具体作用请看 Excel 的“表清单”工作表；字段说明请看“字段字典”工作表。

## 执行顺序

生产环境建议按迁移文件执行：

1. `backend/migrations/001_assistant_core.sql`
2. `backend/migrations/002_langgraph_checkpoint.sql`

合并 DDL 仅用于一次性审阅或初始化新环境，内容与上述顺序一致。对应回滚文件只适用于确认没有正式数据的新环境，不得直接用于生产回滚。

## 重要前置条件

项目目标数据库是 OpenGauss，但当前工作区没有真实 OpenGauss 环境，因此下列内容仍必须由数据库环境完成验收，不能仅凭 SQL 文件视为已验证：

- `JSONB`、`BYTEA`、`BIGSERIAL` 和 `TIMESTAMP WITH TIME ZONE` 类型；
- 复合主键、`ON CONFLICT` 和 Checkpoint 迁移版本写入；
- LangGraph interrupt/resume、pending writes、序列化和并发行为；
- 连接池、事务隔离、行锁以及生产数据量下的索引效果。

应用启动不应自动调用 Checkpointer 的 `setup()` 修改表结构。应先执行显式迁移，再通过健康检查确认 13 张表存在。

## 重新生成

字段定义、表说明和 DDL 来源校验集中维护在生成脚本中。修改迁移或字段说明后，重新运行：

```bash
uv run --no-project --with openpyxl \
  python scripts/generate_database_dictionary.py
```

脚本会检查字段字典中的每张表和每个字段都能在迁移 SQL 中找到，并重新生成 Excel 与合并 DDL。
