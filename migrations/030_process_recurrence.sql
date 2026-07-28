CREATE TABLE IF NOT EXISTS process_recurrences (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id),
    interval_seconds INTEGER NOT NULL,
    max_runs INTEGER NOT NULL,
    run_count INTEGER NOT NULL DEFAULT 0,
    next_due_at TEXT
);