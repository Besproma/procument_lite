-- 仅用于明确回滚一个尚未承载正式数据的新环境。
-- 当前业务数据要求长期保留，生产环境不得未经备份和变更审批直接执行本脚本。

DROP TABLE IF EXISTS trace_spans;
DROP TABLE IF EXISTS user_memories;
DROP TABLE IF EXISTS assistant_ui_blocks;
DROP TABLE IF EXISTS assistant_messages;
DROP TABLE IF EXISTS pending_actions;
DROP TABLE IF EXISTS thread_execution_leases;
DROP TABLE IF EXISTS assistant_runs;
DROP TABLE IF EXISTS scenario_instances;
DROP TABLE IF EXISTS assistant_threads;
