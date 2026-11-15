"""ASGI middleware: request IDs, security headers and request body size limits."""

from __future__ import annotations

import json
import secrets

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_ctx


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


class RequestContextMiddleware:
    """Assigns a request ID, exposes it as ``X-Request-ID`` and adds security headers."""

    def __init__(self, app: ASGIApp, production: bool = False):
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Always server-generated: request IDs are unique keys in the request log, so client-supplied
        # values (which could repeat) are never trusted.
        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)
        is_api = scope.get("path", "").startswith("/api/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}

                def add(key: str, value: str) -> None:
                    if key.encode() not in existing:
                        headers.append((key.encode(), value.encode()))

                add("x-request-id", request_id)
                add("x-content-type-options", "nosniff")
                add("x-frame-options", "DENY")
                add("referrer-policy", "strict-origin-when-cross-origin")
                add("permissions-policy", "camera=(), microphone=(), geolocation=()")
                add("cross-origin-opener-policy", "same-origin")
                if self.production:
                    add("strict-transport-security", "max-age=63072000; includeSubDomains")
                if is_api:
                    add("cache-control", "no-store")
                else:
                    add(
                        "content-security-policy",
                        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                        "script-src 'self'; connect-src 'self'; font-src 'self' data:; "
                        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
                    )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_bytes`` (checks Content-Length and streamed bytes)."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.max_bytes:
                        await self._reject(send)
                        return
                except ValueError:
                    await self._reject(send, status=400, code="bad_request", msg="Invalid Content-Length")
                    return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(send)

    async def _reject(
        self,
        send: Send,
        status: int = 413,
        code: str = "payload_too_large",
        msg: str = "Request body too large",
    ) -> None:
        body = json.dumps({"error": {"code": code, "message": msg, "request_id": request_id_ctx.get()}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(StarletteHTTPException):
    """Raised mid-stream; FastAPI re-raises HTTPExceptions so the JSON error handler renders a 413."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body too large")
