ALTER TABLE execution_graph_nodes ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts > 0);
ALTER TABLE execution_graph_nodes ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0);
ALTER TABLE execution_graph_nodes ADD COLUMN loop_key TEXT;
CREATE INDEX IF NOT EXISTS idx_execution_graph_nodes_loop ON execution_graph_nodes(graph_id, loop_key);

CREATE TABLE IF NOT EXISTS execution_graph_retries (
    graph_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (graph_id, node_id, attempt),
    FOREIGN KEY (graph_id, node_id) REFERENCES execution_graph_nodes(graph_id, node_id)
);

CREATE TRIGGER IF NOT EXISTS execution_graph_retry_attempt_guard
BEFORE INSERT ON execution_graph_retries
WHEN NEW.attempt < 1
BEGIN
    SELECT RAISE(ABORT, 'retry attempt must be positive');
END;

CREATE TRIGGER IF NOT EXISTS execution_graph_retry_budget_guard
BEFORE INSERT ON execution_graph_retries
WHEN NEW.attempt > (SELECT max_attempts FROM execution_graph_nodes WHERE graph_id = NEW.graph_id AND node_id = NEW.node_id)
BEGIN
    SELECT RAISE(ABORT, 'retry budget exceeded');
END;

