"""Test-only persistent SecretStore seam for multi-process E2E runs."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from vesper.secret_store import SecretStoreError


class FileBackedTestSecretStore:
    """Explicit E2E-only backend; stores secrets below a caller-owned temp dir."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "secrets.json"

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, values: dict[str, str]) -> None:
        self.path.write_text(json.dumps(values), encoding="utf-8")

    def put(self, value: str, *, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SecretStoreError("credential is required")
        ref = f"secret://filetest/{label}-{uuid.uuid4().hex}"
        values = self._read()
        values[ref] = value
        self._write(values)
        return ref

    def get(self, ref: str) -> str | None:
        return self._read().get(ref)

    def delete(self, ref: str) -> None:
        values = self._read()
        values.pop(ref, None)
        self._write(values)
