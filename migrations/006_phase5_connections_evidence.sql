CREATE TABLE IF NOT EXISTS capability_catalog (
    capability_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    schema_json TEXT NOT NULL,
    risk_class TEXT NOT NULL DEFAULT 'UNTRUSTED',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS web_evidence (
    evidence_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    query TEXT,
    content_hash TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL,
    content_is_instruction INTEGER NOT NULL DEFAULT 0,
    source_metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS secret_metadata (
    secret_ref TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    backend TEXT NOT NULL DEFAULT 'keychain',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_capability_server ON capability_catalog(server_id);
CREATE INDEX IF NOT EXISTS idx_capability_name ON capability_catalog(name);
CREATE INDEX IF NOT EXISTS idx_evidence_hash ON web_evidence(content_hash);
CREATE INDEX IF NOT EXISTS idx_evidence_retrieved ON web_evidence(retrieved_at);
