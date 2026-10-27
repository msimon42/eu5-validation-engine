"""A small local command API with bounded read projections."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.contracts import PAYLOADS
from backend.app.service import Service
from backend.app.store import Conflict, digest


class BodyBudgetMiddleware:
    """Bound actual received bytes, including requests without Content-Length."""

    def __init__(self, app, limit=16 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.limit):
            response = JSONResponse({"detail": "Invalid or over-budget request body"}, status_code=413)
            return await response(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                response = JSONResponse({"detail": "Request exceeds the 16 MiB transport budget"}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: Literal["create_workspace", "scan", "stage", "decision", "validate", "export", "rollback", "investigate", "cancel", "backup", "runtime_probe", "configure_inference"]
    workspace_id: str | None = None
    payload: dict = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_payload(self):
        self.payload = PAYLOADS[self.command].model_validate(self.payload).model_dump(exclude_none=True)
        return self


def create_app(data_dir: Path | None = None, *, testing: bool = False) -> FastAPI:
    root = Path(data_dir or os.environ.get("EU5_WORKSPACE", Path.cwd() / ".workspace"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = Service(root)
        yield
        app.state.service.close()

    app = FastAPI(title="EU5 Mod Engine", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        allowed = {"localhost", "127.0.0.1", "::1"}
        if testing:
            allowed.add("testserver")
        try:
            host = urlsplit("//" + request.headers.get("host", "")).hostname
        except ValueError:
            host = None
        if host not in allowed:
            return JSONResponse({"detail": "Only local hostnames are accepted"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            permitted = {f"http://{local}:{port}" for local in {"localhost", "127.0.0.1", "[::1]"} for port in {8765, 5173, 4173}}
            permitted.add(str(request.base_url).rstrip("/"))
            if origin and origin not in permitted:
                return JSONResponse({"detail": "Mutating request origin is not permitted"}, status_code=403)
            token = request.headers.get("x-session-token", "")
            if not secrets.compare_digest(token, request.app.state.service.token):
                return JSONResponse({"detail": "Missing installation session capability"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request: Request, exception: Conflict):
        return JSONResponse({"detail": str(exception), "code": "stale_precondition", "action": "refresh_and_reanalyze"}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing_handler(request: Request, exception: KeyError):
        return JSONResponse({"detail": str(exception)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid_handler(request: Request, exception: ValueError):
        return JSONResponse({"detail": str(exception)}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "mode": "local"}

    @app.get("/api/bootstrap")
    def bootstrap(request: Request):
        return request.app.state.service.bootstrap()

    @app.post("/api/commands", status_code=202)
    def command(body: Command, request: Request):
        if body.command != "create_workspace" and not body.workspace_id:
            raise HTTPException(422, "workspace_id is required")
        return request.app.state.service.command(body.model_dump())

    @app.get("/api/workspaces/{identifier}")
    def workspace(identifier: str, request: Request):
        return request.app.state.service.workspace(identifier)

    @app.get("/api/jobs/{identifier}")
    def job(identifier: str, request: Request):
        return request.app.state.service.store.get("job", identifier)

    @app.get("/api/jobs/{identifier}/events")
    async def events(identifier: str, request: Request, after: int = 0):
        service = request.app.state.service
        service.store.get("job", identifier)
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                for event in service.store.events(identifier, cursor):
                    cursor = event["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(event['data'])}\n\n"
                if service.store.get("job", identifier)["state"] in {"completed", "failed", "cancelled"}:
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.3)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/scans/{identifier}")
    def scan(identifier: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        from backend.app.projections import scan_projection
        return scan_projection(request.app.state.service.store.get("scan", identifier), offset, limit)

    @app.get("/api/candidates/{identifier}")
    def candidate(identifier: str, request: Request):
        from backend.app.projections import candidate_projection
        return candidate_projection(request.app.state.service.store.get("candidate", identifier))

    @app.get("/api/evidence/{identifier}")
    def evidence(identifier: str, request: Request):
        from backend.engine.evidence import EvidenceRegistry
        registry = EvidenceRegistry(request.app.state.service.root / "evidence-registry")
        experiments = registry.experiments()
        for experiment in experiments:
            if experiment.get("id", experiment.get("experiment_id")) == identifier:
                return experiment
        try:
            return registry.get_profile(identifier)
        except (KeyError, ValueError):
            raise HTTPException(404, "Evidence record not found")

    @app.get("/api/artifacts/{identifier}")
    def artifact(identifier: str, request: Request):
        service = request.app.state.service
        entry = service.store.get("artifact", identifier)
        path = Path(entry["path"])
        if not path.is_relative_to(service.root) or path.is_symlink() or digest(path.read_bytes()) != entry["sha256"]:
            raise Conflict("Artifact integrity check failed")
        return FileResponse(path, filename=entry["name"], media_type="application/zip")

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="workbench")
    app.add_middleware(BodyBudgetMiddleware)
    return app
