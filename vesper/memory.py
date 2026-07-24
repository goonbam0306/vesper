"""Kernel-owned structured memory and deterministic retrieval."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .storage import Storage


class RetrievalStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICT = "CONFLICT"
    STALE_ONLY = "STALE_ONLY"


@dataclass(frozen=True)
class MemoryObject:
    memory_id: str
    kind: str
    schema_id: str
    schema_version: int
    scope_refs: tuple[str, ...]
    payload: dict[str, Any]
    provenance: dict[str, Any]
    epistemic: str
    validity: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Retrieval:
    status: str
    items: tuple[MemoryObject, ...]
    query: str


class MemoryStore:
    def __init__(self, storage: Storage):
        self.storage = storage

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryObject:
        return MemoryObject(
            memory_id=row["memory_id"], kind=row["kind"], schema_id=row["schema_id"],
            schema_version=row["schema_version"], scope_refs=tuple(json.loads(row["scope_refs_json"])),
            payload=json.loads(row["payload_json"]), provenance=json.loads(row["provenance_json"]),
            epistemic=row["epistemic"], validity=row["validity"], revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def put(self, *, kind: str, payload: dict[str, Any], schema_id: str = "memory", schema_version: int = 1,
            scope_refs: tuple[str, ...] = (), provenance: dict[str, Any] | None = None,
            epistemic: str = "ASSERTED", validity: str = "VALID", memory_id: str | None = None) -> MemoryObject:
        provenance = provenance or {"source": "director"}
        def op(conn: sqlite3.Connection) -> MemoryObject:
            mid = memory_id or str(uuid.uuid4())
            prior = conn.execute("SELECT MAX(revision) FROM memories WHERE memory_id=?", (mid,)).fetchone()[0]
            revision = int(prior or 0) + 1
            now = self._now()
            conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, revision, kind, schema_id, schema_version, json.dumps(scope_refs), json.dumps(payload, sort_keys=True), json.dumps(provenance, sort_keys=True), epistemic, validity, prior, now, now))
            return self._row(conn.execute("SELECT * FROM memories WHERE memory_id=? AND revision=?", (mid, revision)).fetchone())
        return self.storage.write(op)

    def history(self, memory_id: str) -> list[MemoryObject]:
        return self.storage.write(lambda c: [self._row(row) for row in c.execute("SELECT * FROM memories WHERE memory_id=? ORDER BY revision", (memory_id,)).fetchall()])

    def get(self, memory_id: str, revision: int | None = None) -> MemoryObject | None:
        def read(c: sqlite3.Connection) -> MemoryObject | None:
            if revision is None:
                row = c.execute("SELECT * FROM memories WHERE memory_id=? ORDER BY revision DESC LIMIT 1", (memory_id,)).fetchone()
            else:
                row = c.execute("SELECT * FROM memories WHERE memory_id=? AND revision=?", (memory_id, revision)).fetchone()
            return self._row(row) if row else None
        return self.storage.write(read)

    def retrieve(self, query: str, *, scope_refs: tuple[str, ...] = (), limit: int = 10) -> Retrieval:
        terms = [term.lower() for term in query.split() if term]
        def read(c: sqlite3.Connection) -> Retrieval:
            rows = c.execute("SELECT m.* FROM memories m JOIN (SELECT memory_id,MAX(revision) revision FROM memories GROUP BY memory_id) latest ON latest.memory_id=m.memory_id AND latest.revision=m.revision WHERE m.validity='VALID' ORDER BY m.updated_at DESC").fetchall()
            candidates = []
            for row in rows:
                obj = self._row(row)
                if scope_refs and not set(scope_refs).intersection(obj.scope_refs):
                    continue
                text = json.dumps(obj.payload, sort_keys=True).lower()
                score = sum(text.count(term) for term in terms)
                if score:
                    candidates.append((score, obj))
            candidates.sort(key=lambda x: (-x[0], x[1].memory_id))
            items = tuple(obj for _, obj in candidates[:limit])
            if not items:
                status = RetrievalStatus.NOT_FOUND
            elif len(items) > 1 and candidates[0][0] == candidates[1][0]:
                status = RetrievalStatus.AMBIGUOUS
            else:
                status = RetrievalStatus.RESOLVED
            return Retrieval(status=status, items=items, query=query)
        return self.storage.write(read)

    def to_dict(self, obj: MemoryObject) -> dict[str, Any]:
        return asdict(obj)
