"""Command line entrypoints for the local runtime."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path

import uvicorn

from .api import Runtime
from .config import runtime_pid_path, vesper_home


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vesper")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8765)
    sub.add_parser("status")
    sub.add_parser("stop")
    return parser


def _pid_path() -> Path:
    return runtime_pid_path(vesper_home())


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "status":
        path = _pid_path()
        if not path.exists():
            print(json.dumps({"running": False}))
            return 0
        pid = int(path.read_text())
        try:
            os.kill(pid, 0)
        except OSError:
            print(json.dumps({"running": False, "stale_pid": pid}))
        else:
            print(json.dumps({"running": True, "pid": pid}))
        return 0
    if args.command == "stop":
        path = _pid_path()
        if path.exists():
            os.kill(int(path.read_text()), signal.SIGTERM)
            path.unlink(missing_ok=True)
        print("stopped")
        return 0
    if args.host != "127.0.0.1":
        raise SystemExit("refusing non-loopback bind")
    runtime = Runtime()
    runtime.start()
    _pid_path().write_text(str(os.getpid()))
    try:
        uvicorn.run("vesper.api:create_app", host=args.host, port=args.port, factory=True, log_level="info")
    finally:
        runtime.stop()
        _pid_path().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
