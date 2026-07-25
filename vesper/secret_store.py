"""Small local SecretStore boundary for onboarding credentials.

Secret values never cross into SQLite or Vesper event payloads.  SQLite stores
only the opaque keychain:// reference returned by this module.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass


class SecretStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecretStore:
    service: str = "vesper"

    def put(self, value: str, *, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SecretStoreError("credential is required")
        account = f"{label}-{uuid.uuid4().hex}"
        try:
            subprocess.run(
                ["security", "add-generic-password", "-U", "-a", account, "-s", self.service, "-w", value],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError("could not save credential to the local keychain") from exc
        return f"keychain://{self.service}/{account}"

    def get(self, ref: str) -> str | None:
        prefix = f"keychain://{self.service}/"
        if not ref.startswith(prefix):
            return None
        account = ref.removeprefix(prefix)
        try:
            completed = subprocess.run(
                ["security", "find-generic-password", "-a", account, "-s", self.service, "-w"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout.rstrip("\n")

    def delete(self, ref: str) -> None:
        prefix = f"keychain://{self.service}/"
        if not ref.startswith(prefix):
            return
        account = ref.removeprefix(prefix)
        try:
            subprocess.run(
                ["security", "delete-generic-password", "-a", account, "-s", self.service],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError("could not delete credential from the local keychain") from exc


@dataclass
class EphemeralTestSecretStore:
    """Deterministic DI backend for browser/integration tests; never touches Keychain."""
    values: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.values is None:
            self.values = {}

    def put(self, value: str, *, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SecretStoreError("credential is required")
        ref = f"secret://test/{label}-{uuid.uuid4().hex}"
        assert self.values is not None
        self.values[ref] = value
        return ref

    def get(self, ref: str) -> str | None:
        return (self.values or {}).get(ref)

    def delete(self, ref: str) -> None:
        if self.values is not None:
            self.values.pop(ref, None)