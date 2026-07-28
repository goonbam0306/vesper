"""Kernel-owned external capability, web evidence, and MCP normalization boundaries."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request as URLRequest, build_opener

from .artifacts import ArtifactStore
from .context import ContextPack, redact
from .storage import Storage


class ConnectionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CapabilityState(StrEnum):
    REGISTERED = "REGISTERED"
    ELIGIBLE = "ELIGIBLE"
    EXPOSED = "EXPOSED"
    AUTHORIZED = "AUTHORIZED"


@dataclass(frozen=True)
class Capability:
    capability_id: str
    server_id: str
    name: str
    description: str
    schema: dict[str, Any]
    risk_class: str
    effect_class: str = "READ"
    state: CapabilityState = CapabilityState.REGISTERED
    schema_hash: str = ""
    generation: int = 1


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    provider: str
    provider_rank: int
    query: str
    retrieved_at: str
    published_at: str | None = None


@dataclass(frozen=True)
class CrawlPolicy:
    allowed_domains: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...] = ("/",)
    max_pages: int = 20
    max_depth: int = 2
    max_bytes: int = 2_000_000
    per_request_timeout: float = 10.0
    global_timeout: float = 60.0
    rate_limit_per_second: float = 2.0
    respect_robots: bool = True


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title: list[str] = []
        self.links: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.in_title = tag.lower() == "title"
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)
            if self.in_title:
                self.title.append(text)


class _BoundedRedirect(HTTPRedirectHandler):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self.count += 1
        if self.count > self.limit:
            raise ConnectionError("REDIRECT_LIMIT_EXCEEDED", "redirect bound exceeded")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BrowserFallback:
    """An explicit, Vesper-only browser boundary; it never reuses Director browser profiles."""
    def __init__(self, *, profile_root: Path):
        self.profile_root = profile_root.resolve()
        self.profile_root.mkdir(parents=True, exist_ok=True)

    def execute(self, url: str, *, reason: str, max_actions: int, timeout: float, reader: Callable[[str], bytes] | None = None) -> dict[str, Any]:
        if max_actions < 1:
            raise ConnectionError("BROWSER_BUDGET_EXCEEDED", "browser action budget exhausted")
        if timeout <= 0:
            raise ConnectionError("BROWSER_TIMEOUT", "browser timeout must be positive")
        if not reason:
            raise ConnectionError("BROWSER_REASON_REQUIRED", "browser fallback requires an explicit reason")
        data = reader(url) if reader else b""
        return {"url": url, "reason": reason, "profile": str(self.profile_root), "actions_used": 1, "content": data.decode("utf-8", "replace"), "authority": "EVIDENCE_ONLY"}


class ConnectionStore:
    def __init__(self, storage: Storage, *, artifact_store: ArtifactStore | None = None, secret_store: Any | None = None):
        self.storage = storage
        self.artifacts = artifact_store
        self.secret_store = secret_store
        self.search_providers: dict[str, Callable[[str, float], list[dict[str, Any]]]] = {}
        self.metrics: dict[str, float | int] = {"search_latency_ms": 0.0, "search_failures": 0, "fetch_latency_ms": 0.0, "crawl_pages": 0, "crawl_bytes": 0, "capability_resolution_latency_ms": 0.0, "mcp_call_latency_ms": 0.0, "browser_fallback_usage": 0, "page_fault_count": 0, "warm_resume_count": 0}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _cap(row: sqlite3.Row) -> Capability:
        schema = json.loads(row["schema_json"])
        schema_hash = row["schema_hash"] if "schema_hash" in row.keys() else hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        state = CapabilityState(row["state"]) if "state" in row.keys() else (CapabilityState.ELIGIBLE if bool(row["enabled"]) else CapabilityState.REGISTERED)
        return Capability(row["capability_id"], row["server_id"], row["name"], row["description"], schema, row["risk_class"], row["effect_class"] if "effect_class" in row.keys() else "READ", state, schema_hash, int(row["generation"]) if "generation" in row.keys() else 1)

    @staticmethod
    def _credential_ref(ref: str) -> None:
        if not ref.startswith(("keychain://", "secret://", "env://")):
            raise ConnectionError("INVALID_CREDENTIAL_REF", "credentials must be opaque SecretStore references")

    def register_capability(self, *, server_id: str, name: str, description: str = "", schema: dict[str, Any] | None = None, risk_class: str = "UNTRUSTED", effect_class: str = "READ", generation: int = 1) -> dict[str, Any]:
        if not server_id or not name:
            raise ConnectionError("INVALID_CAPABILITY", "server_id and name are required")
        normalized_schema = schema or {}
        schema_hash = hashlib.sha256(json.dumps(normalized_schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        capability_id = str(uuid.uuid4())
        self.storage.write(lambda c: c.execute("INSERT INTO capability_catalog(capability_id,server_id,name,description,schema_json,risk_class,enabled,state,effect_class,schema_hash,generation) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (capability_id, server_id, name, description, json.dumps(normalized_schema, sort_keys=True), risk_class, 0, CapabilityState.REGISTERED, effect_class, schema_hash, generation)))
        return asdict(self._cap(self.storage.write(lambda c: c.execute("SELECT * FROM capability_catalog WHERE capability_id=?", (capability_id,)).fetchone())))

    def set_capability_state(self, capability_id: str, state: CapabilityState) -> dict[str, Any]:
        if state == CapabilityState.AUTHORIZED:
            raise ConnectionError("CAPABILITY_AUTHORIZATION_KERNEL_OWNED", "authorization is granted only by the syscall/permission pipeline")
        allowed = {CapabilityState.REGISTERED: {CapabilityState.ELIGIBLE}, CapabilityState.ELIGIBLE: {CapabilityState.EXPOSED, CapabilityState.REGISTERED}, CapabilityState.EXPOSED: {CapabilityState.ELIGIBLE}}
        def op(c: sqlite3.Connection):
            row = c.execute("SELECT * FROM capability_catalog WHERE capability_id=?", (capability_id,)).fetchone()
            if not row:
                raise ConnectionError("CAPABILITY_NOT_FOUND", capability_id)
            current = CapabilityState(row["state"])
            if state != current and state not in allowed.get(current, set()):
                raise ConnectionError("INVALID_CAPABILITY_TRANSITION", f"{current} -> {state}")
            c.execute("UPDATE capability_catalog SET state=?, enabled=? WHERE capability_id=?", (state, int(state in {CapabilityState.ELIGIBLE, CapabilityState.EXPOSED}), capability_id))
            return c.execute("SELECT * FROM capability_catalog WHERE capability_id=?", (capability_id,)).fetchone()
        return asdict(self._cap(self.storage.write(op)))

    def search_capabilities(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return a bounded, deterministic discovery projection from this runtime's catalog.

        This deliberately does not filter REGISTERED rows: discovery/page-in is not execution
        authority. A unique secondary key prevents SQLite's unspecified tie ordering from
        changing candidate selection when equal names are registered in different orders.
        """
        started = time.perf_counter()
        normalized = " ".join(query.casefold().split())
        pattern = f"%{normalized}%"
        page_limit = max(1, min(limit, 20))

        def read(c: sqlite3.Connection) -> list[sqlite3.Row]:
            return c.execute(
                """
                SELECT capability_id, server_id, name, description, risk_class, state
                FROM capability_catalog
                WHERE lower(name) LIKE ? OR lower(description) LIKE ?
                ORDER BY lower(name) ASC, lower(server_id) ASC, capability_id ASC
                LIMIT ?
                """,
                (pattern, pattern, page_limit),
            ).fetchall()

        rows = self.storage.write(read)
        self.metrics["capability_resolution_latency_ms"] = (time.perf_counter() - started) * 1000
        return [
            {
                "capability_id": row["capability_id"],
                "server_id": row["server_id"],
                "name": row["name"],
                "description": row["description"],
                "risk_class": row["risk_class"],
                "state": row["state"],
            }
            for row in rows
        ]

    def page_capabilities(self, capability_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(capability_ids))
        if len(ids) > 20:
            raise ConnectionError("CAPABILITY_PAGE_TOO_LARGE", "at most 20 capability schemas may be paged into one context")
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.storage.write(lambda c: c.execute(f"SELECT * FROM capability_catalog WHERE capability_id IN ({placeholders})", ids).fetchall())
        by_id = {row["capability_id"]: row for row in rows}
        missing = [item for item in ids if item not in by_id]
        if missing:
            raise ConnectionError("CAPABILITY_NOT_FOUND", f"unknown capability: {missing[0]}")
        # Paging is discovery/context visibility, not execution authority. Registered schemas may be
        # shown in K4 as untrusted metadata, but cannot be invoked until kernel authorization.
        return [asdict(self._cap(by_id[item])) for item in ids]

    def list_capability_stats(self) -> dict[str, int]:
        rows = self.storage.write(lambda c: c.execute("SELECT state, COUNT(*) AS n FROM capability_catalog GROUP BY state").fetchall())
        result = {"registered": 0, "eligible": 0, "exposed": 0, "authorized": 0}
        for row in rows:
            result[str(row["state"]).lower()] = int(row["n"])
        return result

    def register_search_provider(self, provider_id: str, handler: Callable[[str, float], list[dict[str, Any]]]) -> None:
        self.search_providers[provider_id] = handler

    def search(self, query: str, *, providers: list[str] | None = None, timeout: float = 10.0, limit: int = 20) -> list[dict[str, Any]]:
        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        for provider_id in providers or list(self.search_providers):
            handler = self.search_providers.get(provider_id)
            if not handler:
                continue
            try:
                raw_results = handler(query, timeout)
            except Exception:
                self.metrics["search_failures"] = int(self.metrics["search_failures"]) + 1
                continue
            retrieved_at = self._now()
            for rank, raw in enumerate(raw_results, start=1):
                if not raw.get("url"):
                    continue
                results.append(asdict(SearchResult(str(raw["url"]), str(raw.get("title", "")), str(raw.get("snippet", "")), provider_id, rank, query, retrieved_at, raw.get("published_at"))))
                if len(results) >= limit:
                    break
        self.metrics["search_latency_ms"] = (time.perf_counter() - started) * 1000
        return results

    def _fetch_raw(self, url: str, *, max_bytes: int, timeout: float, redirect_limit: int) -> tuple[bytes, str, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConnectionError("INVALID_URL", "only absolute http(s) URLs are allowed")
        if max_bytes <= 0 or max_bytes > 2_000_000:
            raise ConnectionError("INVALID_BUDGET", "max_bytes must be between 1 and 2000000")
        redirect = _BoundedRedirect(redirect_limit)
        request = URLRequest(url, headers={"User-Agent": "VesperResearch/0.1"})
        try:
            with build_opener(redirect).open(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1)
                content_type = response.headers.get("Content-Type", "")
                final_url = response.geturl()
        except ConnectionError:
            raise
        except Exception as exc:
            raise ConnectionError("FETCH_FAILED", str(exc)) from exc
        if len(raw) > max_bytes:
            raise ConnectionError("BYTE_BUDGET_EXCEEDED", "response exceeded max_bytes")
        return raw, content_type, final_url

    def fetch_evidence(self, url: str, *, query: str | None = None, max_bytes: int = 1_000_000, timeout: float = 10.0, redirect_limit: int = 3) -> dict[str, Any]:
        started = time.perf_counter()
        raw, content_type, final_url = self._fetch_raw(url, max_bytes=max_bytes, timeout=timeout, redirect_limit=redirect_limit)
        parser = _TextParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        text = " ".join(parser.parts)
        digest = hashlib.sha256(raw).hexdigest()
        injection_like = bool(re.search(r"ignore (?:all|previous) instructions|system prompt|you are now|api key", text, re.I))
        evidence_id, retrieved_at = str(uuid.uuid4()), self._now()
        artifact_id = self.artifacts.publish(raw, media_type=content_type).artifact_id if self.artifacts else None
        metadata = {"content_type": content_type, "untrusted": True, "instruction_like_text": injection_like, "final_url": final_url, "artifact_id": artifact_id}
        self.storage.write(lambda c: c.execute("INSERT INTO web_evidence(evidence_id,url,retrieved_at,provider,query,content_hash,title,content_text,content_is_instruction,source_metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (evidence_id, final_url, retrieved_at, "direct_http", query, digest, " ".join(parser.title), text, 0, json.dumps(metadata, sort_keys=True))))
        self.metrics["fetch_latency_ms"] = (time.perf_counter() - started) * 1000
        return {"evidence_id": evidence_id, "url": url, "final_url": final_url, "retrieved_at": retrieved_at, "provider": "direct_http", "query": query, "content_hash": digest, "title": " ".join(parser.title), "text": text[:12000], "artifact_id": artifact_id, "epistemic": "OBSERVED", "authority": "EVIDENCE_ONLY", "instruction_like_text": injection_like, "source_provenance": {"kind": "fetch", "requested_url": url, "final_url": final_url, "content_type": content_type}}

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM web_evidence WHERE evidence_id=?", (evidence_id,)).fetchone())
        if not row:
            return None
        metadata = json.loads(row["source_metadata_json"])
        return {"evidence_id": row["evidence_id"], "url": row["url"], "final_url": metadata.get("final_url", row["url"]), "retrieved_at": row["retrieved_at"], "provider": row["provider"], "query": row["query"], "content_hash": row["content_hash"], "title": row["title"], "text": row["content_text"][:12000], "artifact_id": metadata.get("artifact_id"), "epistemic": "OBSERVED", "authority": "EVIDENCE_ONLY", "instruction_like_text": bool(metadata.get("instruction_like_text")), "source_provenance": {"kind": "fetch"}}

    def crawl(self, seed_url: str, policy: CrawlPolicy) -> dict[str, Any]:
        started, frontier, visited, artifact_ids = time.monotonic(), deque([(seed_url, 0)]), [], []
        spent_bytes = 0
        robots_cache: dict[str, set[str]] = {}
        stopped = "FRONTIER_EXHAUSTED"
        while frontier:
            if time.monotonic() - started >= policy.global_timeout:
                stopped = "GLOBAL_TIMEOUT"; break
            if len(visited) >= policy.max_pages:
                stopped = "MAX_PAGES"; break
            url, depth = frontier.popleft()
            if url in visited or depth > policy.max_depth:
                continue
            parsed = urlparse(url)
            if parsed.hostname not in policy.allowed_domains or not any(parsed.path.startswith(prefix) for prefix in policy.allowed_path_prefixes):
                continue
            if policy.respect_robots:
                disallowed = robots_cache.get(parsed.netloc)
                if disallowed is None:
                    try:
                        raw, _, _ = self._fetch_raw(f"{parsed.scheme}://{parsed.netloc}/robots.txt", max_bytes=64_000, timeout=policy.per_request_timeout, redirect_limit=1)
                        disallowed = {line.split(":", 1)[1].strip() for line in raw.decode("utf-8", "replace").splitlines() if line.lower().startswith("disallow:")}
                    except ConnectionError:
                        disallowed = set()
                    robots_cache[parsed.netloc] = disallowed
                if any(parsed.path.startswith(item) for item in disallowed if item):
                    continue
            remaining = policy.max_bytes - spent_bytes
            if remaining <= 0:
                stopped = "MAX_BYTES"; break
            try:
                evidence = self.fetch_evidence(url, max_bytes=min(remaining, 1_000_000), timeout=policy.per_request_timeout, redirect_limit=3)
            except ConnectionError:
                continue
            visited.append(url)
            spent_bytes += len(evidence["text"].encode("utf-8"))
            if evidence.get("artifact_id"):
                artifact_ids.append(evidence["artifact_id"])
            parser = _TextParser(); parser.feed(evidence["text"])
            # Re-fetch raw only for link discovery within the same bounded request budget is deliberately avoided.
            # HTML links are extracted from a bounded direct read when source is text/html.
            try:
                raw, content_type, _ = self._fetch_raw(url, max_bytes=min(remaining, 1_000_000), timeout=policy.per_request_timeout, redirect_limit=3)
                if "html" in content_type:
                    link_parser = _TextParser(); link_parser.feed(raw.decode("utf-8", "replace"))
                    for href in link_parser.links:
                        candidate = urljoin(url, href)
                        if candidate not in visited and depth < policy.max_depth:
                            frontier.append((candidate, depth + 1))
            except ConnectionError:
                pass
            if policy.rate_limit_per_second > 0:
                time.sleep(1 / policy.rate_limit_per_second)
        self.metrics["crawl_pages"] = len(visited); self.metrics["crawl_bytes"] = spent_bytes
        return {"seed_url": seed_url, "visited": visited, "pages_fetched": len(visited), "bytes_fetched": spent_bytes, "artifact_ids": artifact_ids, "stopped_reason": stopped, "provenance": {"kind": "bounded_crawl", "policy": asdict(policy)}}

    def register_mcp_resource(self, server_id: str, uri: str, content: bytes) -> dict[str, Any]:
        resource_id = str(uuid.uuid4())
        artifact_id = self.artifacts.publish(content, media_type="application/octet-stream").artifact_id if self.artifacts else None
        self.storage.write(lambda c: c.execute("INSERT INTO mcp_resources(resource_id,server_id,uri,artifact_id,content_hash) VALUES(?,?,?,?,?)", (resource_id, server_id, uri, artifact_id, hashlib.sha256(content).hexdigest())))
        return {"resource_id": resource_id, "server_id": server_id, "uri": uri, "artifact_id": artifact_id, "authority": "EVIDENCE_ONLY"}

    def read_mcp_resource(self, resource_id: str) -> dict[str, Any]:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM mcp_resources WHERE resource_id=?", (resource_id,)).fetchone())
        if not row:
            raise ConnectionError("MCP_RESOURCE_NOT_FOUND", resource_id)
        return {"resource_id": row["resource_id"], "server_id": row["server_id"], "uri": row["uri"], "artifact_id": row["artifact_id"], "authority": "EVIDENCE_ONLY", "epistemic": "OBSERVED"}

    def register_mcp_prompt(self, server_id: str, name: str, template: str) -> dict[str, Any]:
        prompt_id = str(uuid.uuid4())
        self.storage.write(lambda c: c.execute("INSERT INTO mcp_prompts(prompt_id,server_id,name,template) VALUES(?,?,?,?)", (prompt_id, server_id, name, template)))
        return {"prompt_id": prompt_id, "server_id": server_id, "name": name, "template": template, "authority": "EVIDENCE_ONLY", "kind": "WORKFLOW_TEMPLATE"}

    def mcp_sampling(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"status": "REJECTED", "code": "MCP_SAMPLING_DISABLED", "message": "MCP sampling cannot bypass Vesper Cognitive Runtime"}

    def evidence_context_pack(self, *, k0: dict[str, Any], k1: dict[str, Any], evidence: list[dict[str, Any]]) -> ContextPack:
        safe_evidence = [dict(redact(item), authority="EVIDENCE_ONLY") for item in evidence]
        return ContextPack.build({"K0": redact(k0), "K1": redact(k1), "K3": {"evidence": safe_evidence}})

    def register_secret_metadata(self, *, provider: str, label: str, secret_ref: str) -> dict[str, Any]:
        self._credential_ref(secret_ref)
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO secret_metadata(secret_ref,provider,label) VALUES (?,?,?)", (secret_ref, provider, label)))
        return {"secret_ref": secret_ref, "provider": provider, "label": label, "backend": "keychain"}

    def list_secret_metadata(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.storage.write(lambda c: c.execute("SELECT secret_ref,provider,label,backend,created_at FROM secret_metadata ORDER BY created_at DESC").fetchall())]

    def rotate_secret(self, old_ref: str, value: str, *, label: str) -> str:
        if not old_ref.startswith(("keychain://", "secret://", "env://")):
            raise ConnectionError("INVALID_CREDENTIAL_REF", "credentials must be opaque SecretStore references")
        if self.secret_store is None:
            raise ConnectionError("SECRET_STORE_UNAVAILABLE", "secret rotation requires a secret store")
        new_ref = self.secret_store.put(value, label=label)
        self.storage.write(lambda c: c.execute("DELETE FROM secret_metadata WHERE secret_ref=?", (old_ref,)))
        self.secret_store.delete(old_ref)
        self.register_secret_metadata(provider="rotated", label=label, secret_ref=new_ref)
        return new_ref

    def register_provider_connection(self, *, connection_id: str, display_name: str, base_url: str, api_style: str, credential_ref: str | None = None, headers_ref: str | None = None, endpoint_type: str = "custom", provider: str = "openai-compatible") -> dict[str, Any]:
        if api_style not in {"official", "openai-compatible", "local-compatible"}:
            raise ConnectionError("INVALID_API_STYLE", api_style)
        if credential_ref:
            self._credential_ref(credential_ref)
        if headers_ref:
            self._credential_ref(headers_ref)
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO provider_connections(connection_id,display_name,base_url,api_style,credential_ref,headers_ref,endpoint_type,provider) VALUES(?,?,?,?,?,?,?,?)", (connection_id, display_name, base_url, api_style, credential_ref, headers_ref, endpoint_type, provider)))
        return {"connection_id": connection_id, "display_name": display_name, "base_url": base_url, "api_style": api_style, "credential_ref": credential_ref, "headers_ref": headers_ref, "endpoint_type": endpoint_type, "provider": provider, "has_credential": bool(credential_ref)}

    def provider_connections(self) -> list[dict[str, Any]]:
        """Return safe user-facing connection metadata only.

        Credential references are operational internals and must not cross API
        read boundaries; `has_credential` is sufficient for the UI.
        """
        return [
            {
                "connection_id": row["connection_id"],
                "display_name": row["display_name"],
                "base_url": row["base_url"],
                "api_style": row["api_style"],
                "endpoint_type": row["endpoint_type"],
                "provider": row["provider"],
                "has_credential": bool(row["credential_ref"]),
            }
            for row in self.storage.write(
                lambda c: c.execute(
                    "SELECT connection_id,display_name,base_url,api_style,endpoint_type,provider,credential_ref FROM provider_connections ORDER BY connection_id"
                ).fetchall()
            )
        ]

    def operational_metrics(self) -> dict[str, float | int]:
        return dict(self.metrics)

    def web_research_e2e(self, cognitive: Any, process_id: str, request: Any, query: str, *, search_results: list[SearchResult]) -> dict[str, Any]:
        fault = cognitive.invoke(process_id, request, {"task": "web research", "query": query}, information_need=query)
        self.metrics["page_fault_count"] = int(self.metrics["page_fault_count"]) + 1
        evidence = self.fetch_evidence(search_results[0].url, query=query)
        # External evidence stays in L2 as an observation; it is never promoted to durable semantic memory.
        cognitive.memory.page_in_observation(process_id, evidence)
        attempt = cognitive.resolve_page_fault(fault.attempt_id)
        if attempt.status == "COMPLETED":
            self.metrics["warm_resume_count"] = int(self.metrics["warm_resume_count"]) + 1
        return {"attempt": attempt, "old_pack_id": fault.context_pack_id, "evidence": evidence, "search_result": asdict(search_results[0])}
