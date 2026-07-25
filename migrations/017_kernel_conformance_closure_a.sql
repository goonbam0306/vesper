ALTER TABLE conversation_messages ADD COLUMN process_id TEXT;
ALTER TABLE conversation_messages ADD COLUMN result_process_id TEXT;
ALTER TABLE conversation_messages ADD COLUMN client_request_id TEXT;
CREATE INDEX IF NOT EXISTS idx_conversation_messages_process ON conversation_messages(process_id);