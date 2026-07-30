"""Vesper-owned MCP Gateway and deterministic local/custom sandbox.

This module models MCP as a transport boundary only.  It intentionally contains no
provider SDK, network credential, or native-app integration.  The gateway accepts
only explicit local/custom transports, turns every return value into untrusted
external evidence, and requires a Vesper-owned approval record before a mutation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .connections import CapabilityState, ConnectionError, ConnectionStore
from .storage import Storage


class MCPTransport(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MCPGatewayError(ConnectionError):
    code: str
    message: str

    def __post_init__(self) -> None:
        ConnectionError.__init__(self, self.code, self.message)


class LocalCustomMCPSandbox:
    """A reversible, credential-free MCP test target used only by Vesper tests/demo.

    It supports one observation and one idempotent write.  Tests can inject named
    failures to verify recovery without pretending a provider integration exists.
    """
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {"seed": {"title": "Sandbox observation", "body": "untrusted external text"}}
        self.writes: dict[str, dict[str, Any]] = {}
        self.failure: str | None = None
        self.schema_generation = 1

    def list_tools(self) -> list[dict[str, Any]]:
        if self.failure == "unavailable":
            raise TimeoutError("sandbox unavailable")
        read_schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        if self.schema_generation > 1:
            read_schema["properties"]["include_metadata"] = {"type": "boolean"}
        return [
            {"name": "sandbox.read", "description": "Read untrusted sandbox evidence", "inputSchema": read_schema, "effect_class": "READ", "reversible": True, "idempotent": True, "approval_required": False},
            {"name": "sandbox.write", "description": "Write a reversible sandbox item", "inputSchema": {"type": "object", "required": ["key", "value"], "properties": {"key": {"type": "string"}, "value": {}}}, "effect_class": "WRITE", "reversible": True, "idempotent": True, "approval_required": True},
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.failure == "timeout":
            raise TimeoutError("sandbox timeout")
        if self.failure == "permission":
            raise PermissionError("sandbox permission denied")
        if self.failure == "malformed":
            return {"bad": object()}  # normalized by gateway failure path
        if name == "sandbox.read":
            return {"content": self.items.get(str(arguments.get("key", "seed")), {}), "source": "local-custom-sandbox"}
        if name == "sandbox.write":
            key, value = str(arguments["key"]), arguments["value"]
            self.items[key] = {"value": value}
            self.writes[key] = {"key": key, "value": value}
            if self.failure == "ambiguous":
                raise ConnectionError("MCP_AMBIGUOUS_WRITE", "write may have reached sandbox; reconcile before retry")
            return {"key": key, "status": "written", "source": "local-custom-sandbox"}
        raise ConnectionError("MCP_TOOL_NOT_FOUND", name)


class MCPGateway:
    def __init__(self, storage: Storage, connections: ConnectionStore) -> None:
        self.storage, self.connections = storage, connections
        self.transports: dict[str, MCPTransport] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: Any) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ConnectionError("MCP_MALFORMED_RESULT", "MCP result is not JSON-normalizable") from exc

    @staticmethod
    def _normalize_error(exc: Exception) -> ConnectionError:
        if isinstance(exc, ConnectionError):
            return exc
        if isinstance(exc, TimeoutError):
            return ConnectionError("MCP_TIMEOUT", "MCP transport timed out")
        if isinstance(exc, PermissionError):
            return ConnectionError("MCP_PERMISSION_DENIED", "MCP transport denied permission")
        return ConnectionError("MCP_TRANSPORT_UNAVAILABLE", "MCP transport is unavailable")

    def register_local_server(self, *, server_id: str, display_name: str, transport: MCPTransport) -> dict[str, Any]:
        if not server_id or not display_name:
            raise ConnectionError("MCP_INVALID_SERVER", "server_id and display_name are required")
        self.transports[server_id] = transport
        now = self._now()
        self.storage.write(lambda c: c.execute(
            "INSERT OR REPLACE INTO mcp_servers(server_id,display_name,transport,health,approved_local,config_json,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (server_id, display_name, "local-custom", "REGISTERED", 1, "{}", now, now),
        ))
        return self.server(server_id)

    def server(self, server_id: str) -> dict[str, Any]:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM mcp_servers WHERE server_id=?", (server_id,)).fetchone())
        if not row:
            raise ConnectionError("MCP_SERVER_NOT_FOUND", server_id)
        return {"server_id": row["server_id"], "display_name": row["display_name"], "transport": row["transport"], "health": row["health"], "approved_local": bool(row["approved_local"]), "last_error_code": row["last_error_code"], "last_seen_at": row["last_seen_at"]}

    def _set_health(self, server_id: str, health: str, code: str | None = None) -> None:
        self.storage.write(lambda c: c.execute("UPDATE mcp_servers SET health=?,last_error_code=?,last_seen_at=?,updated_at=? WHERE server_id=?", (health, code, self._now(), self._now(), server_id)))

    def discover(self, server_id: str) -> list[dict[str, Any]]:
        transport = self.transports.get(server_id)
        if transport is None:
            raise ConnectionError("MCP_TRANSPORT_NOT_ATTACHED", server_id)
        try:
            tools = transport.list_tools()
            if not isinstance(tools, list):
                raise ConnectionError("MCP_MALFORMED_RESULT", "list_tools must return list")
            output: list[dict[str, Any]] = []
            for tool in tools:
                name = str(tool.get("name", ""))
                if not name:
                    raise ConnectionError("MCP_MALFORMED_RESULT", "tool name is required")
                schema = dict(tool.get("inputSchema", {}))
                schema_hash = hashlib.sha256(self._json(schema).encode()).hexdigest()
                existing = self.storage.write(lambda c: c.execute("SELECT * FROM capability_catalog WHERE server_id=? AND name=? ORDER BY generation DESC LIMIT 1", (server_id, name)).fetchone())
                generation = 1 if existing is None else int(existing["generation"]) + (1 if existing["schema_hash"] != schema_hash else 0)
                if existing is None or existing["schema_hash"] != schema_hash:
                    capability = self.connections.register_capability(server_id=server_id, name=name, description=str(tool.get("description", "")), schema=schema, risk_class="UNTRUSTED", effect_class=str(tool.get("effect_class", "READ")), generation=generation)
                    # Schema changes re-enter review rather than retaining prior exposure.
                    output.append(dict(capability, approval_required=bool(tool.get("approval_required", str(tool.get("effect_class", "READ")) != "READ")), reversible=bool(tool.get("reversible", False)), idempotent=bool(tool.get("idempotent", False)), schema_review_required=existing is not None))
                else:
                    output.append({"capability_id": existing["capability_id"], "server_id": server_id, "name": name, "state": existing["state"], "effect_class": existing["effect_class"], "schema_hash": schema_hash, "generation": generation, "approval_required": bool(tool.get("approval_required", existing["effect_class"] != "READ")), "reversible": bool(tool.get("reversible", False)), "idempotent": bool(tool.get("idempotent", False)), "schema_review_required": False})
            self._set_health(server_id, "HEALTHY")
            return output
        except Exception as exc:
            error = self._normalize_error(exc)
            self._set_health(server_id, "OFFLINE", error.code)
            raise error

    def read(self, *, server_id: str, capability_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        capability = self.connections.page_capabilities([capability_id])[0]
        if capability["server_id"] != server_id or capability["effect_class"] != "READ":
            raise ConnectionError("MCP_READ_NOT_ALLOWED", "only registered read capability may be observed")
        if CapabilityState(capability["state"]) not in {CapabilityState.ELIGIBLE, CapabilityState.EXPOSED}:
            raise ConnectionError("MCP_CAPABILITY_NOT_EXPOSED", "capability is not Vesper-policy eligible")
        try:
            result = self.transports[server_id].call_tool(capability["name"], arguments)
            payload = self._json(result)
        except Exception as exc:
            error = self._normalize_error(exc); self._set_health(server_id, "OFFLINE", error.code); raise error
        observation_id, now = str(uuid.uuid4()), self._now()
        self.storage.write(lambda c: c.execute("INSERT INTO mcp_observations(observation_id,server_id,capability_id,observed_at,content_json,content_hash,provenance_json) VALUES(?,?,?,?,?,?,?)", (observation_id, server_id, capability_id, now, payload, hashlib.sha256(payload.encode()).hexdigest(), self._json({"transport": "local-custom", "tool": capability["name"], "untrusted": True}))))
        self._set_health(server_id, "HEALTHY")
        return {"observation_id": observation_id, "server_id": server_id, "capability_id": capability_id, "content": json.loads(payload), "observed_at": now, "authority": "EVIDENCE_ONLY", "epistemic": "OBSERVED", "instruction_trust": "UNTRUSTED_EXTERNAL", "provenance": {"transport": "local-custom", "tool": capability["name"]}}

    def propose_write(self, *, server_id: str, capability_id: str, process_id: str, idempotency_key: str) -> dict[str, Any]:
        capability = self.connections.page_capabilities([capability_id])[0]
        if capability["server_id"] != server_id or capability["effect_class"] == "READ":
            raise ConnectionError("MCP_WRITE_NOT_ALLOWED", "capability is not a write/effect")
        effect_id, now = str(uuid.uuid4()), self._now()
        try:
            self.storage.write(lambda c: c.execute("INSERT INTO mcp_effects(effect_id,server_id,capability_id,process_id,idempotency_key,status,proposed_at) VALUES(?,?,?,?,?,?,?)", (effect_id, server_id, capability_id, process_id, idempotency_key, "PENDING_APPROVAL", now)))
        except sqlite3.IntegrityError:
            row = self.storage.write(lambda c: c.execute("SELECT * FROM mcp_effects WHERE server_id=? AND idempotency_key=?", (server_id, idempotency_key)).fetchone())
            return self._effect(row)
        return {"effect_id": effect_id, "status": "PENDING_APPROVAL", "authority": "VESPER_KERNEL", "process_id": process_id}

    def approve_and_execute(self, *, effect_id: str, approved: bool, arguments: dict[str, Any]) -> dict[str, Any]:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM mcp_effects WHERE effect_id=?", (effect_id,)).fetchone())
        if not row:
            raise ConnectionError("MCP_EFFECT_NOT_FOUND", effect_id)
        if row["status"] != "PENDING_APPROVAL":
            return self._effect(row)
        if not approved:
            self.storage.write(lambda c: c.execute("UPDATE mcp_effects SET status='REJECTED',resolved_at=? WHERE effect_id=?", (self._now(), effect_id)))
            return self._effect(self.storage.write(lambda c: c.execute("SELECT * FROM mcp_effects WHERE effect_id=?", (effect_id,)).fetchone()))
        capability = self.connections.page_capabilities([row["capability_id"]])[0]
        try:
            result = self.transports[row["server_id"]].call_tool(capability["name"], arguments)
            receipt = self._json({"receipt_id": str(uuid.uuid4()), "result": result, "tool": capability["name"], "authority": "VESPER_KERNEL"})
            self.storage.write(lambda c: c.execute("UPDATE mcp_effects SET status='CONFIRMED',approved_at=?,resolved_at=?,receipt_json=? WHERE effect_id=?", (self._now(), self._now(), receipt, effect_id)))
            self._set_health(row["server_id"], "HEALTHY")
        except ConnectionError as exc:
            status = "AMBIGUOUS" if exc.code == "MCP_AMBIGUOUS_WRITE" else "FAILED"
            self.storage.write(lambda c: c.execute("UPDATE mcp_effects SET status=?,approved_at=?,resolved_at=?,error_code=? WHERE effect_id=?", (status, self._now(), self._now(), exc.code, effect_id)))
            self._set_health(row["server_id"], "OFFLINE", exc.code)
        except Exception as exc:
            error = self._normalize_error(exc)
            self.storage.write(lambda c: c.execute("UPDATE mcp_effects SET status='FAILED',approved_at=?,resolved_at=?,error_code=? WHERE effect_id=?", (self._now(), self._now(), error.code, effect_id)))
            self._set_health(row["server_id"], "OFFLINE", error.code)
        return self._effect(self.storage.write(lambda c: c.execute("SELECT * FROM mcp_effects WHERE effect_id=?", (effect_id,)).fetchone()))

    def _effect(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"effect_id": row["effect_id"], "server_id": row["server_id"], "capability_id": row["capability_id"], "process_id": row["process_id"], "status": row["status"], "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None, "error_code": row["error_code"], "authority": "VESPER_KERNEL"}

    def overview(self) -> dict[str, Any]:
        servers = [self.server(row["server_id"]) for row in self.storage.write(lambda c: c.execute("SELECT server_id FROM mcp_servers ORDER BY server_id").fetchall())]
        caps = self.connections.search_capabilities("", limit=100)
        observations = [dict(row) for row in self.storage.write(lambda c: c.execute("SELECT observation_id,server_id,capability_id,observed_at,stale,authority FROM mcp_observations ORDER BY observed_at DESC LIMIT 20").fetchall())]
        effects = [self._effect(row) for row in self.storage.write(lambda c: c.execute("SELECT * FROM mcp_effects ORDER BY proposed_at DESC LIMIT 20").fetchall())]
        return {"servers": servers, "capabilities": caps, "observations": observations, "effects": effects}
