"""ModelOps AI FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import (
    alerts,
    analyst,
    analytics,
    auth,
    gateway,
    health,
    pricing,
    projects,
    providers,
    requests,
)
from app.core.config import get_settings
from app.core.errors import error_body, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.providers.registry import close_http_client

logger = logging.getLogger("modelops")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("ModelOps AI %s starting (environment=%s)", __version__, settings.environment)
    if not settings.analyst_configured:
        logger.info("AI Analyst is not configured (AI_ANALYST_PROVIDER/MODEL/API_KEY)")
    yield
    await close_http_client()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="ModelOps AI API",
        version=__version__,
        description="AI API monitoring, observability and cost intelligence.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    # Order: the last added middleware runs first (outermost).
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Request-ID",
                "x-api-key",
                "x-goog-api-key",
                "anthropic-version",
                "anthropic-beta",
            ],
            expose_headers=["X-Request-ID", "x-modelops-request-id", "Retry-After"],
            max_age=600,
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware, production=settings.is_production)

    api = APIRouter(prefix="/api/v1")
    for module in (health, auth, providers, projects, gateway, analytics, requests, pricing, alerts, analyst):
        api.include_router(module.router)
    app.include_router(api)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def api_not_found(path: str):
        return JSONResponse(error_body("not_found", "Endpoint not found"), status_code=404)

    _mount_frontend(app, settings.resolved_static_dir())
    return app


def _mount_frontend(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the built single-page app (same origin as the API) when it is available."""
    if static_dir is None:
        return
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = static_dir / "index.html"
    root = static_dir.resolve()

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str):
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"cache-control": "no-cache"})


app = create_app()
