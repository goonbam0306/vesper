"""Canonical human-visible Ask Vesper transcript projection."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from .storage import Storage


class ConversationStore:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _conversation(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def create(self, process_id: str | None = None) -> dict[str, Any]:
        """Create UI continuity only; process_id is retained solely for legacy schema compatibility."""
        conversation_id = str(uuid.uuid4())
        now = self._now()
        def op(conn: sqlite3.Connection):
            conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?)", (conversation_id, process_id or "", "Ask Vesper", now, now))
            return self._conversation(conn.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone())
        return self.storage.write(op)

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        return self.storage.write(lambda c: (self._conversation(row) if (row := c.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()) else None))

    def list(self) -> list[dict[str, Any]]:
        return self.storage.write(lambda c: [self._conversation(row) for row in c.execute("SELECT * FROM conversations ORDER BY updated_at DESC, conversation_id").fetchall()])

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self.storage.write(lambda c: [self._message(row) for row in c.execute("SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY created_at, message_id", (conversation_id,)).fetchall()])

    def append(self, conversation_id: str, role: str, content: str, *, attempt_id: str | None = None, retry_of: str | None = None, process_id: str | None = None, result_process_id: str | None = None, client_request_id: str | None = None) -> dict[str, Any]:
        if role not in {"USER", "ASSISTANT", "SYSTEM_STATUS", "ERROR"}:
            raise ValueError("invalid conversation message role")
        message_id, now = str(uuid.uuid4()), self._now()
        def op(conn: sqlite3.Connection):
            if conn.execute("SELECT 1 FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone() is None:
                raise ValueError("conversation not found")
            conn.execute("INSERT INTO conversation_messages(message_id,conversation_id,role,content,created_at,attempt_id,retry_of,process_id,result_process_id,client_request_id) VALUES (?,?,?,?,?,?,?,?,?,?)", (message_id, conversation_id, role, content, now, attempt_id, retry_of, process_id, result_process_id, client_request_id))
            conn.execute("UPDATE conversations SET updated_at=? WHERE conversation_id=?", (now, conversation_id))
            return self._message(conn.execute("SELECT * FROM conversation_messages WHERE message_id=?", (message_id,)).fetchone())
        return self.storage.write(op)

    def context_items(self, conversation_id: str, current_prompt: str, limit: int = 6) -> list[dict[str, str]]:
        """Bounded working representation; never returns an arbitrary full transcript."""
        rows = self.messages(conversation_id)
        terms = {term.lower() for term in current_prompt.split() if len(term) > 2}
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, row in enumerate(rows):
            if row["role"] not in {"USER", "ASSISTANT"}:
                continue
            score = sum(row["content"].lower().count(term) for term in terms)
            scored.append((score, index, row))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        selected = [item[2] for item in scored[:limit]]
        selected.sort(key=lambda item: (item["created_at"], item["message_id"]))
        return [{"role": row["role"], "content": row["content"]} for row in selected]