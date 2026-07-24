"""Immutable logical Context Packs and deterministic provider serialization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


FRAME_NAMES = ("K0", "K1", "K2", "K3", "K4", "K5")


@dataclass(frozen=True)
class ContextPack:
    pack_id: str
    frames: Mapping[str, Any]
    fault: str | None = None

    @staticmethod
    def build(frames: Mapping[str, Any], *, fault: str | None = None) -> "ContextPack":
        normalized = {name: frames.get(name) for name in FRAME_NAMES if frames.get(name) is not None}
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        pack_id = "ctx_" + hashlib.sha256(encoded.encode()).hexdigest()[:24]
        return ContextPack(pack_id=pack_id, frames=normalized, fault=fault)

    def serialize(self) -> str:
        return json.dumps({"pack_id": self.pack_id, "frames": self.frames, "fault": self.fault}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def wire_prefix(self) -> str:
        stable = {key: self.frames[key] for key in ("K0", "K2", "K4") if key in self.frames}
        return json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def page_fault(self, reason: str) -> "ContextPack":
        return ContextPack.build(self.frames, fault=reason)


def admit(*, authorized: bool, relevant: bool, current: bool, needed: bool, worth_cost: bool) -> bool:
    return all((authorized, relevant, current, needed, worth_cost))
