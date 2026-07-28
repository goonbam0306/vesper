CREATE TABLE IF NOT EXISTS process_runtime_state (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id),
    budget_tokens_remaining INTEGER,
    budget_seconds_remaining INTEGER,
    monitor_last_check INTEGER,
    monitor_checks INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_process_runtime_state_updated
    ON process_runtime_state(updated_at);
