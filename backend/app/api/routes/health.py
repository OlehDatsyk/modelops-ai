"""Liveness/readiness probes and public metadata."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter(tags=["health"])
logger = logging.getLogger("modelops.health")


def _db_ok() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database health check failed")
        return False


@router.get("/health")
async def health():
    """Readiness: verifies database connectivity. Returns 503 when the database is unreachable."""
    ok = await run_in_threadpool(_db_ok)
    body = {
        "status": "ok" if ok else "degraded",
        "database": "ok" if ok else "unavailable",
        "version": __version__,
    }
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/meta")
async def meta():
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "analyst_configured": settings.analyst_configured,
        "providers": ["openai", "anthropic", "gemini"],
    }
