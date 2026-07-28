CREATE TABLE IF NOT EXISTS lane_invocations (
    invocation_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES processes(process_id),
    lane_id TEXT NOT NULL,
    lane_version INTEGER NOT NULL,
    node_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('CREATED','RUNNING','COMPLETED','FAILED','CANCELLED')),
    input_artifact_refs_json TEXT NOT NULL,
    context_refs_json TEXT NOT NULL,
    tool_grants_json TEXT NOT NULL,
    model_route_id TEXT,
    output_artifact_ref TEXT,
    failure_classification_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (lane_id, lane_version) REFERENCES lane_definitions(lane_id, version)
);
CREATE INDEX IF NOT EXISTS idx_lane_invocations_process ON lane_invocations(process_id, created_at);
