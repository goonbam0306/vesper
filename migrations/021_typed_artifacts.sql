CREATE TABLE IF NOT EXISTS typed_artifacts (
    artifact_id TEXT PRIMARY KEY REFERENCES artifacts(artifact_id),
    artifact_type TEXT NOT NULL CHECK (length(artifact_type) > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    process_id TEXT NOT NULL,
    producer_invocation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    content_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_typed_artifacts_process ON typed_artifacts(process_id);
CREATE INDEX IF NOT EXISTS idx_typed_artifacts_producer ON typed_artifacts(producer_invocation_id);

