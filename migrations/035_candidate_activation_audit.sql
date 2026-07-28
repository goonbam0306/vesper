CREATE TABLE IF NOT EXISTS candidate_activation_audit (
    audit_id TEXT PRIMARY KEY,
    candidate_key TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    FOREIGN KEY(candidate_key) REFERENCES candidate_reviews(candidate_key)
);
CREATE INDEX IF NOT EXISTS idx_candidate_activation_candidate
    ON candidate_activation_audit(candidate_key);
