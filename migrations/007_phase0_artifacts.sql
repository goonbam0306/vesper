CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    media_type TEXT,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);

CREATE TABLE IF NOT EXISTS storage_writer_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    class TEXT NOT NULL,
    queue_depth INTEGER NOT NULL,
    wait_ms REAL NOT NULL,
    transaction_ms REAL NOT NULL,
    wal_bytes INTEGER NOT NULL,
    checkpoint_ms REAL NOT NULL,
    sqlite_busy INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
