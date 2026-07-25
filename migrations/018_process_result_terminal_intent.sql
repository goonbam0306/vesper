ALTER TABLE process_results ADD COLUMN terminal_status TEXT NOT NULL DEFAULT 'COMPLETED';
CREATE INDEX IF NOT EXISTS idx_process_results_terminal_status ON process_results(terminal_status);