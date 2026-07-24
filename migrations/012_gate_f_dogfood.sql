CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS committed_undo (
    undo_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    inverse_patch_json TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    consumed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_undo_resource ON committed_undo(resource_type, resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(decision, created_at DESC);

INSERT OR IGNORE INTO app_settings(setting_key, value_json)
VALUES
    ('developer_diagnostics', 'false'),
    ('model_route', '{"status":"unconfigured"}');
