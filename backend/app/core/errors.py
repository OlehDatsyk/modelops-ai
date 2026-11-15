"""Application errors and sanitised exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

logger = logging.getLogger("modelops.errors")


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, "not_found", f"{what} not found")


def error_body(code: str, message: str, details: object | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message, "request_id": request_id_ctx.get()}}
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Echo only locations and messages — never the submitted input (it may contain secrets).
        details = [
            {"loc": [str(p) for p in err.get("loc", [])], "msg": err.get("msg", "invalid")} for err in exc.errors()
        ]
        return JSONResponse(error_body("validation_error", "Invalid request", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(error_body("internal_error", "An unexpected error occurred"), status_code=500)
