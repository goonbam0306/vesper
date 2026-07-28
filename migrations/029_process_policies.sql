CREATE TABLE IF NOT EXISTS process_policies (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id),
    policy_class TEXT NOT NULL DEFAULT 'normal' CHECK (policy_class IN ('interactive','normal','background','persistent','recurring','monitoring')),
    max_graph_nodes INTEGER NOT NULL DEFAULT 64,
    max_expansion_depth INTEGER NOT NULL DEFAULT 8,
    max_lane_invocations INTEGER NOT NULL DEFAULT 32,
    max_replan_count INTEGER NOT NULL DEFAULT 4,
    retry_budget INTEGER NOT NULL DEFAULT 8,
    deadline_at TEXT,
    cost_token_budget INTEGER,
    approval_boundaries_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS process_timers (
    process_id TEXT PRIMARY KEY REFERENCES processes(process_id),
    due_at TEXT NOT NULL,
    wake_key TEXT NOT NULL,
    claimed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_process_timers_due ON process_timers(due_at, claimed_at);