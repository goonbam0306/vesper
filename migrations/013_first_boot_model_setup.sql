INSERT OR IGNORE INTO app_settings(setting_key, value_json)
VALUES
    ('first_boot_completed', 'false');

CREATE INDEX IF NOT EXISTS idx_provider_connections_display_name
ON provider_connections(display_name);

ALTER TABLE model_routes ADD COLUMN base_url TEXT;
ALTER TABLE model_routes ADD COLUMN connection_id TEXT;
ALTER TABLE model_routes ADD COLUMN api_style TEXT;
ALTER TABLE model_routes ADD COLUMN endpoint_type TEXT NOT NULL DEFAULT 'custom';
ALTER TABLE provider_connections ADD COLUMN endpoint_type TEXT NOT NULL DEFAULT 'custom';
