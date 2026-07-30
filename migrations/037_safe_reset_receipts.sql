CREATE TABLE IF NOT EXISTS safe_reset_receipts (
    reset_key TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    export_id TEXT,
    deleted_at TEXT NOT NULL
);