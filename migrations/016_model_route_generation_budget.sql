ALTER TABLE model_routes ADD COLUMN max_output_tokens INTEGER;

-- NULL deliberately means provider default / no adapter-imposed budget.
-- Existing routes remain valid and are not rewritten.
