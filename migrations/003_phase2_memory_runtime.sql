CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    kind TEXT NOT NULL,
    schema_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    scope_refs_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    epistemic TEXT NOT NULL,
    validity TEXT NOT NULL,
    supersedes_revision INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(memory_id, revision)
);

CREATE TABLE IF NOT EXISTS process_memory_working_set (
    process_id TEXT NOT NULL REFERENCES processes(process_id),
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY(process_id, memory_id)
);

CREATE TABLE IF NOT EXISTS model_routes (
    route_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    privacy TEXT NOT NULL,
    reliability REAL NOT NULL,
    cost REAL NOT NULL,
    latency_ms REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    credential_ref TEXT
);

CREATE TABLE IF NOT EXISTS model_attempts (
    attempt_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO model_routes(route_id,model_id,provider,capabilities_json,privacy,reliability,cost,latency_ms)
VALUES ('local-default','local-small','local','["text"]','local',0.90,0.00,100.0);

CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at);
CREATE INDEX IF NOT EXISTS idx_model_routes_enabled ON model_routes(enabled);
