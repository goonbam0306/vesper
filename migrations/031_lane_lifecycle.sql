ALTER TABLE lane_definitions ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (lifecycle_state IN ('ACTIVE', 'RETIRED', 'SUPERSEDED'));
ALTER TABLE lane_definitions ADD COLUMN superseded_by_version INTEGER;
CREATE INDEX IF NOT EXISTS idx_lane_definitions_lifecycle ON lane_definitions(lane_id, lifecycle_state, version);

UPDATE lane_definitions SET lifecycle_state='RETIRED' WHERE enabled=0 AND lifecycle_state='ACTIVE';
