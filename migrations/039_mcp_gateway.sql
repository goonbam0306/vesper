CREATE TABLE IF NOT EXISTS mcp_servers (
    server_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    transport TEXT NOT NULL DEFAULT 'local-custom',
    health TEXT NOT NULL DEFAULT 'REGISTERED',
    approved_local INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_error_code TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mcp_observations (
    observation_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    authority TEXT NOT NULL DEFAULT 'EVIDENCE_ONLY',
    stale INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mcp_effects (
    effect_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    process_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    proposed_at TEXT NOT NULL,
    approved_at TEXT,
    resolved_at TEXT,
    receipt_json TEXT,
    reconciliation_json TEXT,
    error_code TEXT,
    UNIQUE(server_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_mcp_observations_server ON mcp_observations(server_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_effects_server ON mcp_effects(server_id, status);
CREATE INDEX IF NOT EXISTS idx_mcp_effects_process ON mcp_effects(process_id, status);
