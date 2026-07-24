"""Kernel-owned connection metadata, capability paging, and bounded web evidence."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request as URLRequest, urlopen

from .storage import Storage


class ConnectionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Capability:
    capability_id: str
    server_id: str
    name: str
    description: str
    schema: dict[str, Any]
    risk_class: str


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.in_title = tag.lower() == "title"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)
            if self.in_title:
                self.title.append(text)


class ConnectionStore:
    def __init__(self, storage: Storage):
        self.storage = storage

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _cap(row: sqlite3.Row) -> Capability:
        return Capability(row["capability_id"], row["server_id"], row["name"], row["description"], json.loads(row["schema_json"]), row["risk_class"])

    def register_capability(self, *, server_id: str, name: str, description: str = "", schema: dict[str, Any] | None = None, risk_class: str = "UNTRUSTED") -> dict[str, Any]:
        if not server_id or not name:
            raise ConnectionError("INVALID_CAPABILITY", "server_id and name are required")
        capability_id = str(uuid.uuid4())
        self.storage.write(lambda c: c.execute("INSERT INTO capability_catalog(capability_id,server_id,name,description,schema_json,risk_class) VALUES (?,?,?,?,?,?)", (capability_id, server_id, name, description, json.dumps(schema or {}, sort_keys=True), risk_class)))
        return asdict(self._cap(self.storage.write(lambda c: c.execute("SELECT * FROM capability_catalog WHERE capability_id=?", (capability_id,)).fetchone())))

    def search_capabilities(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        q = f"%{query.lower()}%"
        rows = self.storage.write(lambda c: c.execute("SELECT * FROM capability_catalog WHERE enabled=1 AND (lower(name) LIKE ? OR lower(description) LIKE ?) ORDER BY name LIMIT ?", (q, q, max(1, min(limit, 100)))).fetchall())
        return [{"capability_id": row["capability_id"], "server_id": row["server_id"], "name": row["name"], "description": row["description"], "risk_class": row["risk_class"]} for row in rows]

    def page_capabilities(self, capability_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(capability_ids))
        if len(ids) > 20:
            raise ConnectionError("CAPABILITY_PAGE_TOO_LARGE", "at most 20 capability schemas may be paged into one context")
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.storage.write(lambda c: c.execute(f"SELECT * FROM capability_catalog WHERE enabled=1 AND capability_id IN ({placeholders})", ids).fetchall())
        by_id = {row["capability_id"]: row for row in rows}
        missing = [item for item in ids if item not in by_id]
        if missing:
            raise ConnectionError("CAPABILITY_NOT_FOUND", f"unknown capability: {missing[0]}")
        return [asdict(self._cap(by_id[item])) for item in ids]

    def list_capability_stats(self) -> dict[str, int]:
        row = self.storage.write(lambda c: c.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled FROM capability_catalog").fetchone())
        return {"registered": int(row["total"] or 0), "enabled": int(row["enabled"] or 0)}

    def register_secret_metadata(self, *, provider: str, label: str, secret_ref: str) -> dict[str, Any]:
        if not secret_ref or "secret" in secret_ref.lower() and len(secret_ref) > 120:
            raise ConnectionError("INVALID_SECRET_REF", "store a reference, never a raw secret")
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO secret_metadata(secret_ref,provider,label) VALUES (?,?,?)", (secret_ref, provider, label)))
        return {"secret_ref": secret_ref, "provider": provider, "label": label, "backend": "keychain"}

    def list_secret_metadata(self) -> list[dict[str, Any]]:
        rows = self.storage.write(lambda c: c.execute("SELECT secret_ref,provider,label,backend,created_at FROM secret_metadata ORDER BY created_at DESC").fetchall())
        return [dict(row) for row in rows]

    def fetch_evidence(self, url: str, *, query: str | None = None, max_bytes: int = 1_000_000) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConnectionError("INVALID_URL", "only absolute http(s) URLs are allowed")
        if max_bytes <= 0 or max_bytes > 2_000_000:
            raise ConnectionError("INVALID_BUDGET", "max_bytes must be between 1 and 2000000")
        request = URLRequest(url, headers={"User-Agent": "VesperResearch/0.1"})
        try:
            with urlopen(request, timeout=10) as response:
                raw = response.read(max_bytes + 1)
                content_type = response.headers.get("Content-Type", "")
        except Exception as exc:
            raise ConnectionError("FETCH_FAILED", str(exc)) from exc
        if len(raw) > max_bytes:
            raise ConnectionError("BYTE_BUDGET_EXCEEDED", "response exceeded max_bytes")
        parser = _TextParser()
        parser.feed(raw.decode("utf-8", errors="replace") if "text" in content_type or "html" in content_type else raw.decode("utf-8", errors="replace"))
        text = " ".join(parser.parts)
        digest = hashlib.sha256(raw).hexdigest()
        # This marker is provenance classification only. It never becomes an instruction.
        injection_like = bool(re.search(r"ignore (?:all|previous) instructions|system prompt|you are now", text, re.I))
        evidence_id = str(uuid.uuid4())
        retrieved_at = self._now()
        metadata = {"content_type": content_type, "untrusted": True, "instruction_like_text": injection_like}
        self.storage.write(lambda c: c.execute("INSERT INTO web_evidence(evidence_id,url,retrieved_at,provider,query,content_hash,title,content_text,content_is_instruction,source_metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (evidence_id, url, retrieved_at, "direct_http", query, digest, " ".join(parser.title), text, 0, json.dumps(metadata, sort_keys=True))))
        return {"evidence_id": evidence_id, "url": url, "retrieved_at": retrieved_at, "provider": "direct_http", "query": query, "content_hash": digest, "title": " ".join(parser.title), "text": text[:12000], "epistemic": "OBSERVED", "authority": "EVIDENCE_ONLY", "instruction_like_text": injection_like}

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM web_evidence WHERE evidence_id=?", (evidence_id,)).fetchone())
        if not row:
            return None
        return {"evidence_id": row["evidence_id"], "url": row["url"], "retrieved_at": row["retrieved_at"], "provider": row["provider"], "query": row["query"], "content_hash": row["content_hash"], "title": row["title"], "text": row["content_text"][:12000], "epistemic": "OBSERVED", "authority": "EVIDENCE_ONLY", "instruction_like_text": bool(row["content_is_instruction"])}
