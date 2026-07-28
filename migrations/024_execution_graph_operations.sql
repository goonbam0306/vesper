ALTER TABLE execution_graph_nodes ADD COLUMN operation_name TEXT;
CREATE INDEX IF NOT EXISTS idx_execution_graph_nodes_operation ON execution_graph_nodes(operation_name);

CREATE TABLE IF NOT EXISTS execution_graph_operation_runs (
    graph_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    operation_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STARTED','SUCCEEDED','FAILED')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (graph_id, node_id, attempt),
    FOREIGN KEY (graph_id, node_id) REFERENCES execution_graph_nodes(graph_id, node_id)
);

