"""Runtime path resolution and safe defaults."""

from __future__ import annotations

import os
from pathlib import Path


def vesper_home() -> Path:
    override = os.environ.get("VESPER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "Vesper"
    if sys_platform() == "darwin":
        return Path.home() / "Library/Application Support/Vesper"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "vesper"


def sys_platform() -> str:
    import sys

    return sys.platform


def database_path(home: Path | None = None) -> Path:
    return (home or vesper_home()) / "vesper.sqlite3"


def artifact_root(home: Path | None = None) -> Path:
    return (home or vesper_home()) / "artifacts"


def artifact_staging(home: Path | None = None) -> Path:
    return artifact_root(home) / ".staging"


def runtime_pid_path(home: Path | None = None) -> Path:
    return (home or vesper_home()) / "vesper.pid"


def ensure_runtime_dirs(home: Path | None = None) -> Path:
    root = home or vesper_home()
    root.mkdir(parents=True, exist_ok=True)
    artifact_root(root).mkdir(parents=True, exist_ok=True)
    artifact_staging(root).mkdir(parents=True, exist_ok=True)
    return root
