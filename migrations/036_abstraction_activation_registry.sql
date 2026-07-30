CREATE TABLE IF NOT EXISTS abstraction_activation_registry (
    activation_key TEXT PRIMARY KEY,
    candidate_key TEXT NOT NULL UNIQUE,
    abstraction_kind TEXT NOT NULL,
    canonical_function TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT NOT NULL,
    FOREIGN KEY(candidate_key) REFERENCES candidate_reviews(candidate_key)
);
ALTER TABLE candidate_activation_audit ADD COLUMN activation_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_activation_audit_key
    ON candidate_activation_audit(activation_key);

-- The registry and receipt are written in the same Storage writer transaction.
-- Existing rows from migration 035 remain valid with a nullable backfilled receipt key.