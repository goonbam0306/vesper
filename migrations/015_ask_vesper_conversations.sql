CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'Ask Vesper',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    role TEXT NOT NULL CHECK(role IN ('USER','ASSISTANT','SYSTEM_STATUS','ERROR')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempt_id TEXT,
    retry_of TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
    ON conversation_messages(conversation_id, created_at, message_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated
    ON conversations(updated_at DESC);