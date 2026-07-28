ALTER TABLE process_memory_working_set ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE process_memory_working_set ADD COLUMN checkpointed_at TEXT;