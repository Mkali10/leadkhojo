"""FastAPI application factory.

Startup order matters: rules are loaded and validated before the server
accepts traffic, so a malformed rule pack fails the boot loudly instead of
surfacing as a 500 on someone's fortieth site.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from leadkhojo import __version__
from leadkhojo.api import deps
from leadkhojo.api.routers import (
    businesses_router,
    exports_router,
    health_router,
    meta_router,
    scans_router,
)
from leadkhojo.core.config import Settings, get_settings
from leadkhojo.core.errors import LeadKhojoError
from leadkhojo.core.logging import configure_logging
from leadkhojo.db.session import dispose_engine, get_sessionmaker
from leadkhojo.jobs.worker import WorkerPool
from leadkhojo.plugins.registry import build_engine

logger = logging.getLogger(__name__)

DESCRIPTION = """
**LeadKhojo** turns public websites into qualified sales opportunities.

Enter a keyword or a list of domains. LeadKhojo discovers businesses, crawls
their public sites, detects technology and security posture, converts the
findings into concrete opportunities, scores every lead, and exports the
result as CSV or PDF.

### How to run a scan

1. `POST /api/v1/scans` (or `/scans/csv`) → returns `202` with a scan id
2. Poll `GET /api/v1/scans/{id}/progress` every ~2s until the status is
   terminal (`completed`, `failed`, `cancelled`)
3. `GET /api/v1/scans/{id}/businesses` for results — rows appear as they
   finish, so this is useful before the scan ends
4. `GET /api/v1/exports/scans/{id}/csv` or `/pdf`

### What this API will never do

* Return a contact it did not find. `primary_email` is often `null`, and
  that is a correct answer — addresses are never guessed.
* Return a finding without evidence.
* Let a model invent a fact. Opportunity text is produced deterministically
  by the rule engine; the optional AI rewrite is a separate field.

### Note on authentication

There is none in v1. Do not expose this instance to the internet.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    if settings.binds_publicly:
        logger.warning(
            "server.public_bind_without_auth",
            extra={
                "host": settings.host,
                "warning": (
                    "This instance has NO authentication and is bound to a public "
                    "interface. Anyone who can reach it can run scans that appear "
                    "to originate from your IP address."
                ),
            },
        )

    # Load rules now. A malformed pack must fail the boot, not a request.
    engine = build_engine(settings.rules_dir, disabled=settings.disabled_plugins)
    deps.set_plugin_engine(engine)
    logger.info("plugins.loaded", extra={"plugins": list(engine.plugin_ids)})

    sessionmaker: async_sessionmaker = get_sessionmaker(settings)
    pool = WorkerPool(settings=settings, sessionmaker=sessionmaker, engine=engine)
    deps.set_worker_pool(pool)
    await pool.start()

    try:
        yield
    finally:
        await pool.stop()
        deps.set_worker_pool(None)
        deps.set_plugin_engine(None)
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    app = FastAPI(
        title="LeadKhojo API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "LeadKhojo", "url": "https://leadkhojo.com/bot"},
    )
    # Read by the lifespan and by get_app_settings, so a test can hand the
    # app its own configuration instead of the process-wide one.
    app.state.settings = resolved

    # The SPA is served from a different origin in development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Correlation-Id"],
    )

    _register_middleware(app)
    _register_error_handlers(app)

    for router in (health_router, scans_router, businesses_router, exports_router, meta_router):
        prefix = "" if router is health_router else "/api/v1"
        app.include_router(router, prefix=prefix)

    return app


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_and_logging(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id

        # Health checks would otherwise dominate the log.
        if not request.url.path.endswith(("/healthz", "/readyz")):
            logger.info(
                "http.request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "correlation_id": correlation_id,
                },
            )
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def _register_error_handlers(app: FastAPI) -> None:
    """RFC 9457 Problem Details for every error path."""

    @app.exception_handler(LeadKhojoError)
    async def handle_domain_error(request: Request, exc: LeadKhojoError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        if exc.status_code >= 500:
            logger.error(
                "api.internal_error",
                extra={"code": exc.code, "correlation_id": correlation_id},
            )
        return JSONResponse(status_code=exc.status_code, content=exc.to_problem(correlation_id))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Report every invalid field at once.

        Failing on the first one makes the user iterate a single mistake at
        a time.
        """
        errors = [
            {
                "field": ".".join(str(p) for p in error["loc"][1:]) or str(error["loc"][0]),
                "code": error["type"],
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "type": "https://docs.leadkhojo.com/errors/validation-failed",
                "title": "Validation failed",
                "status": 422,
                "detail": f"{len(errors)} field(s) failed validation.",
                "code": "validation_failed",
                "correlation_id": getattr(request.state, "correlation_id", None),
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.exception("api.unhandled_error", extra={"correlation_id": correlation_id})
        return JSONResponse(
            status_code=500,
            content={
                "type": "https://docs.leadkhojo.com/errors/internal-error",
                "title": "Internal error",
                "status": 500,
                # Never leak the exception text: it can contain a crawled
                # page fragment or a connection string.
                "detail": "Something went wrong on our side. Quote the correlation id.",
                "code": "internal_error",
                "correlation_id": correlation_id,
            },
        )


app = create_app()

__all__ = ["app", "create_app", "lifespan"]
