PRAGMA foreign_keys = OFF;

CREATE TABLE effects_gate_c (
    effect_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES processes(process_id),
    operation TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RESERVED','COMMITTED','UNKNOWN_EFFECT','CONFIRMED_APPLIED','CONFIRMED_NOT_APPLIED','STILL_UNKNOWN','REJECTED')),
    output_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO effects_gate_c(effect_id,process_id,operation,fingerprint,status,output_json,created_at,updated_at)
SELECT effect_id,process_id,operation,fingerprint,
       CASE WHEN status='RECONCILED' THEN 'CONFIRMED_APPLIED' ELSE status END,
       output_json,created_at,updated_at
FROM effects;
DROP TABLE effects;
ALTER TABLE effects_gate_c RENAME TO effects;

ALTER TABLE approvals ADD COLUMN parent_approval_id TEXT REFERENCES approvals(approval_id);
ALTER TABLE approvals ADD COLUMN root_approval_id TEXT;
ALTER TABLE approvals ADD COLUMN lineage_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS permission_requests (
    request_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES processes(process_id),
    operation TEXT NOT NULL,
    resource_selector TEXT NOT NULL,
    requested_uses INTEGER,
    state TEXT NOT NULL CHECK (state IN ('PENDING','GRANTED','DENIED','REVOKED')),
    granted_rule_id TEXT REFERENCES authority_rules(rule_id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_permission_requests_process ON permission_requests(process_id);
CREATE INDEX IF NOT EXISTS idx_effect_fingerprint_status ON effects(process_id, operation, fingerprint, status);

PRAGMA foreign_keys = ON;
