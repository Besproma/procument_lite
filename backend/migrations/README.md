# 数据库迁移说明

`001_assistant_core.sql` 创建采购助手自有业务表，`002_langgraph_checkpoint.sql` 创建
LangGraph 官方 Checkpointer 3.1.1 的显式表结构。回滚脚本只允许在无正式数据的新环境使用。

`uv.lock` 已锁定 `langgraph-checkpoint-postgres`，但当前仍没有目标 OpenGauss 环境，因此
尚未把官方 Checkpointer 表迁移误报为已兼容。`002` 已按当前锁定版本提取最终结构，
但接入生产前仍必须在目标 OpenGauss 验证 `checkpoint`、`blob`、`pending writes`、
暂停恢复和并发行为。应用启动时不得用 `setup()` 静默改表；上述迁移和兼容性验证完成前，
生产 `/health/ready` 不得视为通过。

数据库设计交付物：

- `docs/database/procurement_assistant_data_dictionary.xlsx`：表清单、字段字典、索引约束、
  状态枚举、逻辑关系和执行说明。
- `docs/database/procurement_assistant_schema.sql`：把 `001` 和 `002` 合并后的完整建表 DDL。
- `scripts/generate_database_dictionary.py`：从字段定义生成 Excel，并校验 DDL 没有漏表或漏字段。

重新生成 Excel 和完整 DDL：

```bash
uv run --no-project --with openpyxl python scripts/generate_database_dictionary.py
```
