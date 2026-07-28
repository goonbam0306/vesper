CREATE TABLE IF NOT EXISTS candidate_reviews (
    candidate_key TEXT PRIMARY KEY,
    supporting_fallback_ids_json TEXT NOT NULL,
    canonical_function TEXT NOT NULL,
    recommended_abstraction TEXT NOT NULL,
    recommendation_reason TEXT NOT NULL DEFAULT '',
    activation_status TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    approval_id TEXT,
    decided_at TEXT,
    activated INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_reviews_decision ON candidate_reviews(decision);
