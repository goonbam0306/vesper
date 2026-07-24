-- Migration version 6 must not duplicate an already-recorded earlier version.
CREATE TABLE IF NOT EXISTS memory_relations (
    source_memory_id TEXT NOT NULL,
    target_memory_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    required_authority TEXT,
    PRIMARY KEY(source_memory_id, target_memory_id, relation_type)
);

CREATE TABLE IF NOT EXISTS context_manifests (
    context_pack_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    parent_context_pack_id TEXT,
    frames_json TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    model_route_id TEXT,
    token_estimate INTEGER NOT NULL,
    stable_prefix_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cognitive_attempts (
    attempt_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    context_pack_id TEXT NOT NULL,
    route_id TEXT,
    status TEXT NOT NULL,
    failure_classification TEXT,
    information_need TEXT,
    parent_attempt_id TEXT,
    page_fault_count INTEGER NOT NULL DEFAULT 0,
    warm_resume_latency_ms REAL,
    telemetry_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cognitive_attempts_process ON cognitive_attempts(process_id, created_at);
CREATE INDEX IF NOT EXISTS idx_context_manifests_process ON context_manifests(process_id, created_at);
