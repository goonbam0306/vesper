"""Provider-neutral adapter boundary; external data is never trusted instruction."""
from dataclasses import dataclass
from typing import Any


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterEnvelope:
    adapter_id: str
    item_id: str
    payload: dict[str, Any]
    provenance: dict[str, str]
    trusted_instruction: bool = False


class LocalAdapterBoundary:
    def __init__(self, adapter_id: str) -> None:
        if not adapter_id:
            raise ValueError("adapter_id is required")
        self.adapter_id = adapter_id
        self.offline = False
        self.effects: dict[str, dict[str, Any]] = {}

    def set_offline(self, value: bool) -> None:
        self.offline = value

    def read(self, item_id: str, *, payload: dict[str, Any], source_uri: str) -> AdapterEnvelope:
        return AdapterEnvelope(self.adapter_id, item_id, dict(payload), {"adapter_id": self.adapter_id, "source_uri": source_uri})

    def write(self, item_id: str, payload: dict[str, Any], *, approval_id: str | None = None) -> bool:
        if approval_id is None:
            raise AdapterError("adapter write requires Kernel approval")
        if self.offline:
            return False
        self.effects[item_id] = dict(payload)
        return True