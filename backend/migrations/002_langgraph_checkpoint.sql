-- LangGraph PostgreSQL Checkpointer 3.1.1 的最终表结构。
--
-- 执行顺序：先执行 001_assistant_core.sql，再执行本文件。
-- 本文件把官方迁移的最终结果固化为可审阅 SQL，不在应用启动时调用 setup() 静默改表。
--
-- 重要：当前项目尚未在目标 OpenGauss 版本完成兼容性验收。正式执行前必须验证
-- JSONB、BYTEA、复合主键、ON CONFLICT 和 LangGraph interrupt/resume 行为。

CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx
    ON checkpoints (thread_id);

CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx
    ON checkpoint_blobs (thread_id);

CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx
    ON checkpoint_writes (thread_id);

-- 记录官方 Checkpointer 3.1.1 已包含的迁移版本，便于未来由同版本工具检查状态。
INSERT INTO checkpoint_migrations (v)
VALUES (0), (1), (2), (3), (4), (5), (6), (7), (8), (9)
ON CONFLICT (v) DO NOTHING;

COMMENT ON TABLE checkpoint_migrations IS
    'LangGraph Checkpointer migration version history';
COMMENT ON TABLE checkpoints IS
    'LangGraph graph checkpoint metadata and serialized state';
COMMENT ON TABLE checkpoint_blobs IS
    'LangGraph channel value blobs referenced by checkpoint versions';
COMMENT ON TABLE checkpoint_writes IS
    'LangGraph pending task writes associated with a checkpoint';
