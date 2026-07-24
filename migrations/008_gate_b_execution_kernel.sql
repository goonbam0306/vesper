CREATE TABLE IF NOT EXISTS process_waits (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id) ON DELETE CASCADE,
    reason TEXT NOT NULL CHECK (reason IN ('approval','user_input','external_io','timer','child','resource')),
    wake_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_process_waits_wake_key ON process_waits(wake_key);

CREATE TABLE IF NOT EXISTS process_dependencies (
    process_id TEXT NOT NULL REFERENCES processes(process_id) ON DELETE CASCADE,
    depends_on_process_id TEXT NOT NULL REFERENCES processes(process_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (process_id, depends_on_process_id),
    CHECK (process_id <> depends_on_process_id)
);

CREATE INDEX IF NOT EXISTS idx_process_dependencies_dependency ON process_dependencies(depends_on_process_id);

CREATE TABLE IF NOT EXISTS process_authority (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id) ON DELETE CASCADE,
    authority_json TEXT NOT NULL DEFAULT '[]',
    delegable_authority_json TEXT NOT NULL DEFAULT '[]',
    delegation_package_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS watch_cursors (
    cursor INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO watch_cursors(cursor, created_at)
VALUES (0, CURRENT_TIMESTAMP);
