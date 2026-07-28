CREATE TABLE IF NOT EXISTS lane_definitions (
    lane_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    name TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_schema_json TEXT NOT NULL,
    output_schema_json TEXT NOT NULL,
    context_policy_json TEXT NOT NULL,
    tool_profile_json TEXT NOT NULL,
    permission_ceiling_json TEXT NOT NULL,
    capability_requirements_json TEXT NOT NULL,
    model_policy_json TEXT NOT NULL,
    escalation_policy_json TEXT NOT NULL,
    stop_conditions_json TEXT NOT NULL,
    evaluation_contract_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (lane_id, version)
);

CREATE INDEX IF NOT EXISTS idx_lane_definitions_enabled
    ON lane_definitions(lane_id, enabled, version);
CREATE INDEX IF NOT EXISTS idx_lane_definitions_order
    ON lane_definitions(lane_id, version);

