CREATE TABLE IF NOT EXISTS processes (
    process_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('CREATED','RUNNING','WAITING','PAUSED','COMPLETED','FAILED','CANCELLED')),
    origin TEXT NOT NULL,
    entry_event_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    volatile INTEGER NOT NULL DEFAULT 0,
    parent_process_id TEXT REFERENCES processes(process_id),
    FOREIGN KEY (entry_event_id) REFERENCES event_journal(event_id)
);

CREATE TABLE IF NOT EXISTS process_results (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id),
    outputs_json TEXT NOT NULL DEFAULT '{}',
    effects_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS command_requests (
    client_request_id TEXT PRIMARY KEY,
    command_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_event_journal_sequence ON event_journal(sequence);
