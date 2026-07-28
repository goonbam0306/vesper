CREATE TABLE IF NOT EXISTS execution_graph_revisions (
    graph_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('REQUESTED','APPROVED','REJECTED')),
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    approved_by TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    PRIMARY KEY (graph_id, revision_id),
    FOREIGN KEY (graph_id) REFERENCES execution_graphs(graph_id)
);

CREATE INDEX IF NOT EXISTS idx_execution_graph_revisions_status
ON execution_graph_revisions(graph_id, status, created_at);

