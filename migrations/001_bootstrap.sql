CREATE TABLE IF NOT EXISTS director_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    preferred_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS connection_metadata (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    label TEXT,
    secret_ref TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_journal (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    process_id TEXT,
    sequence INTEGER,
    actor TEXT NOT NULL DEFAULT 'kernel',
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);