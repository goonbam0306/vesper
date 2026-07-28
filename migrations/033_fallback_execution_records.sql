CREATE TABLE IF NOT EXISTS fallback_execution_records (
    fallback_execution_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    work_unit_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    inferred_function_label TEXT NOT NULL,
    domain_tags_json TEXT NOT NULL DEFAULT '[]',
    cognitive_operations_json TEXT NOT NULL DEFAULT '[]',
    normalized_input_shape_json TEXT NOT NULL DEFAULT '{}',
    normalized_output_shape_json TEXT NOT NULL DEFAULT '{}',
    normalized_context_shape_json TEXT NOT NULL DEFAULT '{}',
    tool_profile_json TEXT NOT NULL DEFAULT '[]',
    evaluation_dimensions_json TEXT NOT NULL DEFAULT '[]',
    permission_shape_json TEXT NOT NULL DEFAULT '[]',
    selected_model_route TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    disposition TEXT NOT NULL,
    verification_ref TEXT,
    latency_ms REAL,
    cost_json TEXT,
    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
    semantic_metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (process_id) REFERENCES processes(process_id)
);
CREATE INDEX IF NOT EXISTS idx_fallback_execution_process ON fallback_execution_records(process_id, created_at);
CREATE INDEX IF NOT EXISTS idx_fallback_execution_function ON fallback_execution_records(inferred_function_label);
CREATE INDEX IF NOT EXISTS idx_fallback_execution_disposition ON fallback_execution_records(disposition);
