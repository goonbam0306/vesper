ALTER TABLE execution_graph_revisions ADD COLUMN target_node_ids_json TEXT NOT NULL DEFAULT '[]';
CREATE INDEX IF NOT EXISTS idx_execution_graph_revisions_targets ON execution_graph_revisions(graph_id, revision_id);
