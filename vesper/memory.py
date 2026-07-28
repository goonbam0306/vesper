"""Kernel-owned structured memory, process-local residency, and deterministic retrieval."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, replace
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
    status: RetrievalStatus
    items: tuple[MemoryObject, ...]
    query: str


@dataclass(frozen=True)
class ContextPack:
    status: RetrievalStatus
    items: tuple[MemoryObject, ...]
    query: str
    token_budget: int


class WorkingSetState(StrEnum):
    ACTIVE = "ACTIVE"
    CHECKPOINTED = "CHECKPOINTED"
    EVICTED = "EVICTED"
    DISCARDED = "DISCARDED"


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

    def latest(self) -> list[MemoryObject]:
        return self.storage.write(self._latest)

    def get(self, memory_id: str, revision: int | None = None) -> MemoryObject | None:
        def read(c: sqlite3.Connection) -> MemoryObject | None:
            if revision is None:
                row = c.execute("SELECT * FROM memories WHERE memory_id=? ORDER BY revision DESC LIMIT 1", (memory_id,)).fetchone()
            else:
                row = c.execute("SELECT * FROM memories WHERE memory_id=? AND revision=?", (memory_id, revision)).fetchone()
            return self._row(row) if row else None
        return self.storage.write(read)

    def page_in(self, process_id: str, memory: MemoryObject) -> None:
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO process_memory_working_set(process_id,memory_id,revision) VALUES(?,?,?)", (process_id, memory.memory_id, memory.revision)))

    def checkpoint(self, process_id: str) -> tuple[MemoryObject, ...]:
        """Durably mark the current L2 working set as checkpointed without deleting it."""
        now = self._now()
        self.storage.write(lambda c: c.execute("UPDATE process_memory_working_set SET lifecycle_state='CHECKPOINTED', checkpointed_at=? WHERE process_id=?", (now, process_id)))
        return self.l2(process_id)

    def evict(self, process_id: str, memory_id: str) -> MemoryObject | None:
        """Remove one item from active L2 residency; the durable memory remains retrievable."""
        item = self.get(memory_id)
        self.storage.write(lambda c: c.execute("DELETE FROM process_memory_working_set WHERE process_id=? AND memory_id=?", (process_id, memory_id)))
        return item

    def discard(self, process_id: str) -> tuple[MemoryObject, ...]:
        """Discard process-local residency only; this never deletes durable memory."""
        items = self.l2(process_id)
        self.storage.write(lambda c: c.execute("DELETE FROM process_memory_working_set WHERE process_id=?", (process_id,)))
        return items

    def promote(self, process_id: str, memory_id: str) -> MemoryObject | None:
        """Promote an L2 item by returning its durable latest revision."""
        item = self.get(memory_id)
        if item is not None:
            self.page_in(process_id, item)
        return item

    def page_in_observation(self, process_id: str, evidence: dict[str, Any]) -> MemoryObject:
        """Create process-local, non-durable external evidence for one Context Pack resume."""
        observation = self.put(
            kind="external_observation",
            payload={"text": evidence.get("text", ""), "title": evidence.get("title", ""), "url": evidence.get("final_url") or evidence.get("url")},
            schema_id="external_evidence",
            scope_refs=(),
            provenance={"source": "external", "evidence_id": evidence.get("evidence_id"), "content_hash": evidence.get("content_hash"), "artifact_id": evidence.get("artifact_id")},
            epistemic="OBSERVED",
            validity="VALID",
        )
        self.page_in(process_id, observation)
        return observation

    def l2(self, process_id: str) -> tuple[MemoryObject, ...]:
        return tuple(self.storage.write(lambda c: [self._row(row) for row in c.execute("SELECT m.* FROM process_memory_working_set w JOIN memories m ON m.memory_id=w.memory_id AND m.revision=w.revision WHERE w.process_id=? ORDER BY m.memory_id", (process_id,)).fetchall()]))

    def relate(self, source_memory_id: str, target_memory_id: str, relation_type: str, *, required_authority: str | None = None) -> None:
        self.storage.write(lambda c: c.execute("INSERT OR IGNORE INTO memory_relations(source_memory_id,target_memory_id,relation_type,required_authority) VALUES(?,?,?,?)", (source_memory_id, target_memory_id, relation_type, required_authority)))

    def _latest(self, conn: sqlite3.Connection) -> list[MemoryObject]:
        rows = conn.execute("SELECT m.* FROM memories m JOIN (SELECT memory_id,MAX(revision) revision FROM memories GROUP BY memory_id) latest ON latest.memory_id=m.memory_id AND latest.revision=m.revision ORDER BY m.memory_id").fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _score(obj: MemoryObject, terms: list[str]) -> tuple[int, int]:
        text = json.dumps(obj.payload, sort_keys=True).lower()
        lexical = sum(text.count(term) for term in terms)
        # Local deterministic semantic projection: token overlap, intentionally rebuildable and non-canonical.
        token_set = set(text.replace("\"", " ").replace("{", " ").replace("}", " ").replace(":", " ").replace(",", " ").split())
        semantic = sum(1 for term in terms if term in token_set)
        return lexical, semantic

    def retrieve(self, query: str, *, scope_refs: tuple[str, ...] = (), process_id: str | None = None,
                 lane_id: str | None = None, artifact_type: str | None = None, artifact_id: str | None = None,
                 artifact_producer: str | None = None, work_unit_id: str | None = None,
                 authority: tuple[str, ...] = (), limit: int = 10, relation_depth: int = 1, relation_limit: int = 10) -> Retrieval:
        terms = [term.lower() for term in query.split() if term]
        if not terms:
            return Retrieval(RetrievalStatus.INSUFFICIENT, (), query)
        if relation_depth < 0 or relation_depth > 3 or relation_limit < 0:
            raise ValueError("relation traversal bounds invalid")

        def read(c: sqlite3.Connection) -> Retrieval:
            latest = self._latest(c)
            authorized = [obj for obj in latest if (not scope_refs or set(scope_refs).intersection(obj.scope_refs))]
            valid = [obj for obj in authorized if obj.validity == "VALID"]
            filters = {
                "process_id": process_id,
                "lane_id": lane_id,
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "artifact_producer": artifact_producer,
                "work_unit_id": work_unit_id,
            }
            for key, expected in filters.items():
                if expected is not None:
                    valid = [obj for obj in valid if obj.provenance.get(key) == expected]
            stale = [obj for obj in authorized if obj.validity != "VALID"]
            for key, expected in filters.items():
                if expected is not None:
                    stale = [obj for obj in stale if obj.provenance.get(key) == expected]
            scored: list[tuple[int, int, MemoryObject]] = []
            for obj in valid:
                lexical, semantic = self._score(obj, terms)
                if lexical or semantic:
                    scored.append((lexical, semantic, obj))
            scored.sort(key=lambda item: (-item[0], -item[1], item[2].created_at, item[2].memory_id))
            if not scored:
                stale_matches = [obj for obj in stale if any(score for score in self._score(obj, terms))]
                return Retrieval(RetrievalStatus.STALE_ONLY if stale_matches else RetrievalStatus.NOT_FOUND, tuple(stale_matches[:limit]), query)

            selected = [item[2] for item in scored[:limit]]
            selected_ids = {item.memory_id for item in selected}
            frontier = list(selected_ids)
            visited = set(selected_ids)
            for _ in range(relation_depth):
                if not frontier or len(selected) >= relation_limit:
                    break
                placeholders = ",".join("?" for _ in frontier)
                rows = c.execute(f"SELECT source_memory_id,target_memory_id,required_authority FROM memory_relations WHERE source_memory_id IN ({placeholders}) ORDER BY source_memory_id,target_memory_id", frontier).fetchall()
                next_frontier: list[str] = []
                for row in rows:
                    if len(selected) >= relation_limit:
                        break
                    if row["required_authority"] and row["required_authority"] not in authority:
                        continue
                    candidate_id = row["target_memory_id"]
                    if candidate_id in visited:
                        continue
                    candidate = next((obj for obj in valid if obj.memory_id == candidate_id), None)
                    if candidate and (not scope_refs or set(scope_refs).intersection(candidate.scope_refs)):
                        selected.append(candidate)
                        visited.add(candidate_id)
                        next_frontier.append(candidate_id)
                frontier = next_frontier

            values = {json.dumps(obj.payload, sort_keys=True) for obj in selected}
            status = RetrievalStatus.CONFLICT if len(values) > 1 and len(scored) > 1 and scored[0][0:2] == scored[1][0:2] else (RetrievalStatus.AMBIGUOUS if len(scored) > 1 and scored[0][0:2] == scored[1][0:2] else RetrievalStatus.RESOLVED)
            projected = tuple(replace(obj, provenance={**obj.provenance, "retrieval": {"lexical_semantic": self._score(obj, terms), "relation_depth": relation_depth}}) for obj in selected[:limit])
            return Retrieval(status, projected, query)
        return self.storage.write(read)

    def admit_context_pack(self, query: str, *, token_budget: int, limit: int = 10, scope_refs: tuple[str, ...] = (), process_id: str | None = None, lane_id: str | None = None, artifact_type: str | None = None, artifact_id: str | None = None, artifact_producer: str | None = None, work_unit_id: str | None = None, authority: tuple[str, ...] = ()) -> ContextPack:
        if token_budget < 1:
            raise ValueError("token_budget must be positive")
        if limit < 1:
            raise ValueError("limit must be positive")
        retrieval = self.retrieve(
            query,
            scope_refs=scope_refs,
            process_id=process_id,
            lane_id=lane_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            artifact_producer=artifact_producer,
            work_unit_id=work_unit_id,
            authority=authority,
            limit=limit,
        )
        remaining = token_budget
        selected: list[MemoryObject] = []
        for item in retrieval.items:
            encoded = json.dumps(item.payload, sort_keys=True, ensure_ascii=False)
            cost = max(1, len(encoded.split()))
            if cost > remaining:
                continue
            selected.append(item)
            remaining -= cost
        return ContextPack(retrieval.status, tuple(selected), query, token_budget)

    def page_in_pack(self, process_id: str, pack: ContextPack) -> None:
        if not isinstance(pack, ContextPack):
            raise ValueError("ContextPack is required")
        for item in pack.items:
            self.page_in(process_id, item)

    def archive(self, process_id: str) -> tuple[MemoryObject, ...]:
        def op(conn: sqlite3.Connection) -> tuple[MemoryObject, ...]:
            exists = conn.execute("SELECT 1 FROM processes WHERE process_id=?", (process_id,)).fetchone()
            if not exists:
                raise ValueError("process not found")
            rows = conn.execute("SELECT m.* FROM process_memory_working_set w JOIN memories m ON m.memory_id=w.memory_id AND m.revision=w.revision WHERE w.process_id=?", (process_id,)).fetchall()
            now = self._now()
            for row in rows:
                conn.execute("UPDATE memories SET validity='ARCHIVED',updated_at=? WHERE memory_id=? AND revision=?", (now, row["memory_id"], row["revision"]))
            conn.execute("DELETE FROM process_memory_working_set WHERE process_id=?", (process_id,))
            return tuple(self._row(row) for row in rows)
        return self.storage.write(op)

    def compress(self, source_memory_ids: tuple[str, ...], *, summary: str) -> MemoryObject:
        if not source_memory_ids:
            raise ValueError("source memories are required")
        if not summary.strip():
            raise ValueError("summary is required")
        def op(conn: sqlite3.Connection) -> MemoryObject:
            placeholders = ",".join("?" for _ in source_memory_ids)
            rows = conn.execute(f"SELECT * FROM memories WHERE memory_id IN ({placeholders}) AND revision IN (SELECT MAX(revision) FROM memories GROUP BY memory_id)", source_memory_ids).fetchall()
            if len(rows) != len(set(source_memory_ids)):
                raise ValueError("source memory not found")
            now = self._now()
            for row in rows:
                conn.execute("UPDATE memories SET validity='ARCHIVED',updated_at=? WHERE memory_id=? AND revision=?", (now, row["memory_id"], row["revision"]))
            mid = str(uuid.uuid4())
            provenance = {"source": "compression", "compression": {"source_memory_ids": list(source_memory_ids)}}
            conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, 1, "summary", "memory_summary", 1, "[]", json.dumps({"text": summary}, sort_keys=True), json.dumps(provenance, sort_keys=True), "DERIVED", "VALID", None, now, now))
            return self._row(conn.execute("SELECT * FROM memories WHERE memory_id=? AND revision=1", (mid,)).fetchone())
        return self.storage.write(op)

    def to_dict(self, obj: MemoryObject) -> dict[str, Any]:
        return asdict(obj)
