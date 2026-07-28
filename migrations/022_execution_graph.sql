CREATE TABLE IF NOT EXISTS execution_graphs (
    graph_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_graph_nodes (
    graph_id TEXT NOT NULL REFERENCES execution_graphs(graph_id),
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL CHECK (node_type IN ('LANE','DETERMINISTIC_OPERATION','APPROVAL_WAIT','USER_INPUT_WAIT')),
    status TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
    dependencies_json TEXT NOT NULL,
    parent_node_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (graph_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_execution_graph_nodes_graph ON execution_graph_nodes(graph_id);
CREATE INDEX IF NOT EXISTS idx_execution_graph_nodes_parent ON execution_graph_nodes(graph_id, parent_node_id);

CREATE TABLE IF NOT EXISTS execution_graph_edges (
    graph_id TEXT NOT NULL,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    condition_json TEXT,
    PRIMARY KEY (graph_id, from_node_id, to_node_id),
    FOREIGN KEY (graph_id, from_node_id) REFERENCES execution_graph_nodes(graph_id, node_id),
    FOREIGN KEY (graph_id, to_node_id) REFERENCES execution_graph_nodes(graph_id, node_id)
);

