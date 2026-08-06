-- 仅允许在没有正式业务数据的新环境回滚。
-- 生产环境不得直接执行；Checkpoint 删除会使所有暂停场景无法恢复。

DROP TABLE IF EXISTS checkpoint_writes;
DROP TABLE IF EXISTS checkpoint_blobs;
DROP TABLE IF EXISTS checkpoints;
DROP TABLE IF EXISTS checkpoint_migrations;
