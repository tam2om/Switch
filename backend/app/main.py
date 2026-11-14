"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import client_ip, is_allowed_network
from app.api.v1 import (
    admin,
    alerts,
    auth,
    backups,
    integrations,
    inventory,
    jobs,
    monitoring,
    simulator,
    switches,
    topology,
    users,
    vlans,
)
from app.core.config import get_settings
from app.core.redact import configure_logging
from app.db.session import session_factory

log = logging.getLogger("anm")
VERSION = "1.0.0"


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging()
    if s.environment == "production":
        problems = s.validate_for_runtime()
        if problems:
            raise RuntimeError("Refusing to start: " + "; ".join(problems))
    app = FastAPI(title="Aruba Network Manager API", version=VERSION,
                  description="Internal API for centralised management of Aruba AOS-Switch fleets. "
                              "All endpoints require an authenticated session except /auth/login and /health.",
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")

    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                           allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Content-Type", "X-CSRF-Token"])

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        ip = client_ip(request)
        if request.url.path not in ("/health", "/health/ready") and not is_allowed_network(ip):
            log.warning("blocked request from non-authorised network %s to %s", ip, request.url.path)
            return JSONResponse({"detail": {"code": "network_denied",
                                            "message": "Access is restricted to authorised internal networks"}},
                                status_code=403)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'" \
            if not request.url.path.startswith("/api/docs") else \
            "default-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; " \
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "validation_error", "message": "Invalid request",
                                        "details": {"errors": errors}}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": {"code": "internal_error", "message": "Internal server error"}},
                            status_code=500)

    prefix = "/api/v1"
    for r in (auth.router, users.router, switches.router, inventory.router, vlans.router, monitoring.router,
              jobs.router, backups.router, alerts.router, topology.router, admin.router, integrations.router,
              simulator.router):
        app.include_router(r, prefix=prefix)

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok", "version": VERSION}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> JSONResponse:
        try:
            with session_factory()() as db:
                db.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready"})
        except Exception:  # noqa: BLE001
            return JSONResponse({"status": "database unavailable"}, status_code=503)

    @app.get(f"{prefix}/setup/status", tags=["auth"])
    def setup_status() -> dict:
        from sqlalchemy import func, select

        from app.models import User

        with session_factory()() as db:
            n = db.execute(select(func.count()).select_from(User)).scalar_one()
        return {"initialized": n > 0, "version": VERSION, "simulator_enabled": s.simulator_enabled}

    return app


app = create_app()
