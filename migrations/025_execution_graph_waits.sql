CREATE TABLE IF NOT EXISTS execution_graph_waits (
    graph_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    wait_key TEXT NOT NULL,
    resumed INTEGER NOT NULL DEFAULT 0 CHECK (resumed IN (0,1)),
    payload_json TEXT,
    created_at TEXT NOT NULL,
    resumed_at TEXT,
    PRIMARY KEY (graph_id, node_id),
    FOREIGN KEY (graph_id, node_id) REFERENCES execution_graph_nodes(graph_id, node_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_graph_wait_key
ON execution_graph_waits(graph_id, wait_key)
WHERE resumed = 0;
