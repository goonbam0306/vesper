ALTER TABLE capability_catalog ADD COLUMN state TEXT NOT NULL DEFAULT 'REGISTERED';
ALTER TABLE capability_catalog ADD COLUMN effect_class TEXT NOT NULL DEFAULT 'READ';
ALTER TABLE capability_catalog ADD COLUMN schema_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE capability_catalog ADD COLUMN generation INTEGER NOT NULL DEFAULT 1;
UPDATE capability_catalog
SET schema_hash = 'legacy:' || capability_id
WHERE schema_hash = '';

CREATE TABLE IF NOT EXISTS provider_connections (
    connection_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_style TEXT NOT NULL,
    credential_ref TEXT,
    headers_ref TEXT
);

CREATE TABLE IF NOT EXISTS mcp_resources (
    resource_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    uri TEXT NOT NULL,
    artifact_id TEXT,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_prompts (
    prompt_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    name TEXT NOT NULL,
    template TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capability_state ON capability_catalog(state);
CREATE INDEX IF NOT EXISTS idx_mcp_resource_server ON mcp_resources(server_id);
