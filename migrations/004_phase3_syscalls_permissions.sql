CREATE TABLE IF NOT EXISTS syscall_registry (
    operation TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    exposure TEXT NOT NULL DEFAULT 'REGISTERED'
);

CREATE TABLE IF NOT EXISTS authority_rules (
    rule_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    resource_selector TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('ALLOW','ASK','DENY')),
    constraints_json TEXT NOT NULL DEFAULT '{}',
    delegable INTEGER NOT NULL DEFAULT 0,
    issuer TEXT NOT NULL,
    expires_at TEXT,
    uses_remaining INTEGER,
    parent_rule_id TEXT REFERENCES authority_rules(rule_id),
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES processes(process_id),
    syscall_fingerprint TEXT NOT NULL,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    args_json TEXT NOT NULL,
    precondition_json TEXT NOT NULL DEFAULT '{}',
    decision TEXT NOT NULL CHECK (decision IN ('PENDING','APPROVED','REJECTED','EDITED')),
    one_shot INTEGER NOT NULL DEFAULT 1,
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS effects (
    effect_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES processes(process_id),
    operation TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RESERVED','COMMITTED','UNKNOWN_EFFECT','RECONCILED','REJECTED')),
    output_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_authority_operation ON authority_rules(operation);
CREATE INDEX IF NOT EXISTS idx_approval_process ON approvals(process_id);
CREATE INDEX IF NOT EXISTS idx_effect_process ON effects(process_id);

INSERT OR IGNORE INTO syscall_registry(operation,namespace,schema_json,risk,exposure)
VALUES ('test.echo','test','{"type":"object","required":["message"]}','LOW','EXPOSED');
INSERT OR IGNORE INTO syscall_registry(operation,namespace,schema_json,risk,exposure)
VALUES ('test.effect','test','{"type":"object","required":["value"]}','HIGH','EXPOSED');
INSERT OR IGNORE INTO syscall_registry(operation,namespace,schema_json,risk,exposure)
VALUES ('permission.request','permission','{"type":"object","required":["operation","target"]}','HIGH','EXPOSED');
INSERT OR IGNORE INTO authority_rules(rule_id,operation,resource_selector,decision,issuer,delegable)
VALUES ('root-test-echo','test.echo','*','ALLOW','director',1);
INSERT OR IGNORE INTO authority_rules(rule_id,operation,resource_selector,decision,issuer,delegable)
VALUES ('root-test-effect','test.effect','*','ASK','director',0);
INSERT OR IGNORE INTO authority_rules(rule_id,operation,resource_selector,decision,issuer,delegable)
VALUES ('root-permission-request','permission.request','*','ALLOW','director',0);
