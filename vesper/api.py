"""Loopback System API bootstrap subset."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ensure_runtime_dirs, vesper_home
from .storage import Storage


class Runtime:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or vesper_home()
        ensure_runtime_dirs(self.home)
        self.storage = Storage(self.home / "vesper.sqlite3")
        self.bootstrap_token = secrets.token_urlsafe(32)

    def start(self) -> None:
        self.storage.migrate()
        self.storage.start()

    def stop(self) -> None:
        self.storage.stop()



def create_app(runtime: Runtime | None = None) -> FastAPI:
    instance = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        instance.start()
        try:
            yield
        finally:
            instance.stop()

    app = FastAPI(title="Vesper", version="0.1.0", lifespan=lifespan)
    app.state.runtime = instance
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Vesper-Bootstrap"],
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        if not (host.startswith("127.0.0.1") or host.startswith("localhost")):
            return JSONResponse({"detail": "loopback host required"}, status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-vesper-bootstrap") != instance.bootstrap_token:
            return JSONResponse({"detail": "bootstrap session required"}, status_code=401)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' http://127.0.0.1 http://localhost"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": "ready", "bind": "127.0.0.1"}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, str]:
        return {"session": instance.bootstrap_token}

    @app.get("/api/director")
    def director():
        row = instance.storage.write(lambda conn: conn.execute("SELECT preferred_name FROM director_profile WHERE id = 1").fetchone())
        return {"preferred_name": row["preferred_name"] if row else None}

    @app.post("/api/director")
    async def update_director(request: Request):
        body = await request.json()
        preferred_name = body.get("preferred_name")
        if preferred_name is not None and not isinstance(preferred_name, str):
            raise HTTPException(status_code=422, detail="preferred_name must be a string or null")
        instance.storage.write(
            lambda conn: conn.execute(
                "INSERT INTO director_profile(id, preferred_name) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET preferred_name=excluded.preferred_name, updated_at=CURRENT_TIMESTAMP",
                (preferred_name,),
            )
        )
        return {"preferred_name": preferred_name}

    frontend = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets") if (frontend / "assets").exists() else None

        @app.get("/")
        def index():
            return FileResponse(frontend / "index.html")

    return app
