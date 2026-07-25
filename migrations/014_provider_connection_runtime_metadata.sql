ALTER TABLE provider_connections ADD COLUMN provider TEXT NOT NULL DEFAULT 'openai-compatible';

CREATE INDEX IF NOT EXISTS idx_provider_connections_provider
ON provider_connections(provider);
