"""Immutable logical Context Packs and deterministic provider serialization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


FRAME_NAMES = ("K0", "K1", "K2", "K3", "K4", "K5")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=lambda item: dict(item) if isinstance(item, Mapping) else list(item))


@dataclass(frozen=True)
class ContextPack:
    pack_id: str
    frames: Mapping[str, Any]
    fault: str | None = None

    @staticmethod
    def build(frames: Mapping[str, Any], *, fault: str | None = None) -> "ContextPack":
        normalized = {name: frames.get(name) for name in FRAME_NAMES if frames.get(name) is not None}
        # Deterministic semantic identity. A page-fault resume changes `fault` or frames and therefore receives a new ID.
        digest = hashlib.sha256(_json({"frames": normalized, "fault": fault}).encode("utf-8")).hexdigest()[:24]
        return ContextPack(pack_id="ctx_" + digest, frames=_freeze(normalized), fault=fault)

    def serialize(self) -> str:
        return _json({"pack_id": self.pack_id, "frames": self.frames, "fault": self.fault})

    def wire_prefix(self) -> str:
        # K0 plus only stable provider/broker material belongs to a reusable cache prefix.
        return _json({"K0": self.frames.get("K0", {})})

    def dynamic_suffix(self) -> str:
        return _json({key: self.frames[key] for key in FRAME_NAMES if key != "K0" and key in self.frames})

    def page_fault(self, reason: str) -> "ContextPack":
        """Return a new immutable L1 pack that marks the yielded logical call."""
        return ContextPack.build(dict(self.frames), fault=reason)


def admit(*, authorized: bool, relevant: bool, current: bool, needed: bool, worth_cost: bool) -> bool:
    return all((authorized, relevant, current, needed, worth_cost))


def redact(value: Any) -> Any:
    """Redact secret-bearing fields before evidence reaches a manifest or provider wire request."""
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if any(token in key.lower() for token in ("secret", "token", "password", "api_key", "credential")) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, list):
        return tuple(redact(item) for item in value)
    return value
