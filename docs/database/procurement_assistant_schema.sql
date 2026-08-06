-- 采购智能助手完整数据库建表 DDL（参考合并版）
--
-- 执行顺序等同于：001_assistant_core.sql -> 002_langgraph_checkpoint.sql。
-- 本文件便于一次性审阅/初始化新环境；生产变更仍建议按两份迁移文件逐步执行。
-- 当前目标 OpenGauss 兼容性尚未完成生产验收，执行前必须验证 JSONB、BYTEA、复合主键、
-- ON CONFLICT、带时区时间、LangGraph interrupt/resume 和并发行为。

-- ===== BEGIN 001_assistant_core.sql =====

-- 采购智能助手核心业务表。
--
-- 执行前必须在目标 OpenGauss 版本验证 JSONB、BIGSERIAL、ON CONFLICT 和带时区时间
-- 类型兼容性。迁移命令应使用最小 DDL 权限账号；应用运行账号只需 DML 权限。

CREATE TABLE IF NOT EXISTS assistant_threads (
    thread_id VARCHAR(80) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    active_scenario_instance_id VARCHAR(80),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assistant_threads_user_updated
    ON assistant_threads (user_id, updated_at);

CREATE TABLE IF NOT EXISTS scenario_instances (
    scenario_instance_id VARCHAR(80) PRIMARY KEY,
    thread_id VARCHAR(80) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    scenario_id VARCHAR(100) NOT NULL,
    input_source VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    current_wait_group_id VARCHAR(80),
    ended_at TIMESTAMP WITH TIME ZONE,
    end_reason VARCHAR(100),
    CHECK (input_source IN ('button', 'natural_language')),
    CHECK (status IN ('running', 'waiting', 'completed', 'aborted', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_scenario_thread_status
    ON scenario_instances (thread_id, status);
CREATE INDEX IF NOT EXISTS idx_scenario_expiry_status
    ON scenario_instances (expires_at, status);

CREATE TABLE IF NOT EXISTS assistant_runs (
    run_id VARCHAR(80) PRIMARY KEY,
    thread_id VARCHAR(80) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    trace_id VARCHAR(80) NOT NULL,
    input_type VARCHAR(64) NOT NULL,
    scenario_instance_id VARCHAR(80),
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    error_code VARCHAR(100),
    CHECK (status IN ('running', 'succeeded', 'failed', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_runs_thread_started
    ON assistant_runs (thread_id, started_at);
CREATE INDEX IF NOT EXISTS idx_runs_trace
    ON assistant_runs (trace_id);

CREATE TABLE IF NOT EXISTS thread_execution_leases (
    thread_id VARCHAR(80) PRIMARY KEY,
    run_id VARCHAR(80) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    action_id VARCHAR(80) PRIMARY KEY,
    wait_group_id VARCHAR(80) NOT NULL,
    thread_id VARCHAR(80) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    scenario_instance_id VARCHAR(80) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    input_schema_id VARCHAR(100) NOT NULL,
    status VARCHAR(32) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    consumed_by_run_id VARCHAR(80),
    CHECK (status IN ('pending', 'consumed', 'invalidated', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_actions_thread_status_expiry
    ON pending_actions (thread_id, status, expires_at);
CREATE INDEX IF NOT EXISTS idx_actions_wait_group
    ON pending_actions (wait_group_id);

CREATE TABLE IF NOT EXISTS assistant_messages (
    message_id VARCHAR(100) PRIMARY KEY,
    thread_id VARCHAR(80) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    run_id VARCHAR(80) NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CHECK (role IN ('user', 'assistant'))
);

CREATE INDEX IF NOT EXISTS idx_messages_thread_created
    ON assistant_messages (thread_id, created_at);

-- UI 块与消息分开保存：消息只存可展示文字，UI 块存经过 Pydantic 校验的结构化事件。
CREATE TABLE IF NOT EXISTS assistant_ui_blocks (
    block_id BIGSERIAL PRIMARY KEY,
    thread_id VARCHAR(80) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    block_json JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ui_blocks_thread_id
    ON assistant_ui_blocks (thread_id, block_id);

CREATE TABLE IF NOT EXISTS user_memories (
    user_id VARCHAR(128) PRIMARY KEY,
    memory_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    source_run_id VARCHAR(80),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_error VARCHAR(1000)
);

CREATE TABLE IF NOT EXISTS trace_spans (
    span_id VARCHAR(80) PRIMARY KEY,
    trace_id VARCHAR(80) NOT NULL,
    parent_span_id VARCHAR(80),
    run_id VARCHAR(80) NOT NULL,
    thread_id VARCHAR(80) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    span_kind VARCHAR(32) NOT NULL,
    name VARCHAR(200) NOT NULL,
    target VARCHAR(200),
    attempt INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    duration_ms DOUBLE PRECISION,
    first_byte_ms DOUBLE PRECISION,
    first_text_delta_ms DOUBLE PRECISION,
    final_result_ms DOUBLE PRECISION,
    input_json JSONB,
    output_json JSONB,
    error_code VARCHAR(100),
    attributes_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    CHECK (attempt >= 1),
    CHECK (status IN ('RUNNING', 'OK', 'ERROR', 'CANCELLED'))
);

CREATE INDEX IF NOT EXISTS idx_trace_trace_started
    ON trace_spans (trace_id, started_at);
CREATE INDEX IF NOT EXISTS idx_trace_run
    ON trace_spans (run_id);
CREATE INDEX IF NOT EXISTS idx_trace_name_started
    ON trace_spans (name, started_at);
CREATE INDEX IF NOT EXISTS idx_trace_status_started
    ON trace_spans (status, started_at);

-- ===== END 001_assistant_core.sql =====

-- ===== BEGIN 002_langgraph_checkpoint.sql =====

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

-- ===== END 002_langgraph_checkpoint.sql =====
