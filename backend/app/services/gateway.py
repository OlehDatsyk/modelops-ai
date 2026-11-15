"""Gateway forwarding: credentials, budgets, upstream call, usage capture and recording."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anyio
import httpx
from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import GatewayIdentity
from app.core.crypto import DecryptionError, decrypt_secret
from app.core.errors import error_body
from app.db.session import get_sessionmaker
from app.models import ProviderCredential
from app.providers.base import (
    ProviderAdapter,
    UpstreamRequest,
    Usage,
    classify_status,
    extract_error_message,
)
from app.providers.registry import get_http_client
from app.services.alerts import blocking_budget, evaluate_after_request
from app.services.usage import RequestRecord, record_request

logger = logging.getLogger("modelops.gateway")

_PASSTHROUGH_HEADERS = ("retry-after", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests")


class GatewayCall:
    def __init__(
        self,
        request: Request,
        background: BackgroundTasks,
        ident: GatewayIdentity,
        adapter: ProviderAdapter,
        endpoint: str,
    ):
        self.request = request
        self.background = background
        self.ident = ident
        self.adapter = adapter
        self.endpoint = endpoint
        self.request_id: str = request.state.request_id

    # --- recording ------------------------------------------------------------------
    def _record_sync(
        self,
        *,
        model: str,
        streamed: bool,
        http_status: int,
        latency_ms: int,
        usage: Usage,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        session = get_sessionmaker()()
        try:
            record_request(
                session,
                RequestRecord(
                    request_id=self.request_id,
                    user_id=self.ident.user_id,
                    project_id=self.ident.project_id,
                    api_key_id=self.ident.api_key_id,
                    provider=self.adapter.name,
                    model=model,
                    endpoint=self.endpoint,
                    streamed=streamed,
                    http_status=http_status,
                    latency_ms=latency_ms,
                    usage=usage,
                    error_type=error_type,
                    error_message=error_message,
                ),
            )
            if error_type == "invalid_credentials":
                cred = session.scalar(
                    select(ProviderCredential).where(
                        ProviderCredential.user_id == self.ident.user_id,
                        ProviderCredential.provider == self.adapter.name,
                    )
                )
                if cred is not None:
                    cred.status = "invalid"
                    cred.status_message = "The provider rejected this key during a gateway request."
                    session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to record gateway request")
        finally:
            session.close()

    async def record(self, **kwargs: Any) -> None:
        # Shield so the record is written even if the client disconnects mid-stream.
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(lambda: self._record_sync(**kwargs))
        self.background.add_task(evaluate_after_request, self.ident.user_id, self.ident.project_id)

    async def reject(self, status: int, code: str, message: str, model: str = "") -> JSONResponse:
        """Return a gateway-generated error and record it as a failed request."""
        await self.record(
            model=model,
            streamed=False,
            http_status=status,
            latency_ms=0,
            usage=Usage(),
            error_type=code,
            error_message=message,
        )
        return JSONResponse(error_body(code, message), status_code=status, headers=self._headers())

    def _headers(self, upstream: httpx.Response | None = None) -> dict[str, str]:
        headers = {"x-modelops-request-id": self.request_id}
        if upstream is not None:
            for name in _PASSTHROUGH_HEADERS:
                if name in upstream.headers:
                    headers[name] = upstream.headers[name]
        return headers

    # --- pre-flight -------------------------------------------------------------------
    def _load_key_sync(self) -> tuple[str | None, str | None, str | None]:
        """Returns (api_key, error_code, error_message)."""
        session = get_sessionmaker()()
        try:
            cred = session.scalar(
                select(ProviderCredential).where(
                    ProviderCredential.user_id == self.ident.user_id,
                    ProviderCredential.provider == self.adapter.name,
                )
            )
            if cred is None:
                return (
                    None,
                    "provider_not_configured",
                    (f"No {self.adapter.display_name} API key is configured for this account."),
                )
            try:
                api_key = decrypt_secret(cred.encrypted_key)
            except DecryptionError:
                return (
                    None,
                    "credential_unavailable",
                    ("The stored provider key cannot be decrypted. Re-enter it in Providers."),
                )
            budget = blocking_budget(session, self.ident.user_id, self.ident.project_id)
            if budget is not None:
                return (
                    None,
                    "budget_exceeded",
                    (
                        f"Budget '{budget.name}' ({budget.period}, ${budget.limit_usd:.2f}) has been reached; "
                        "requests are blocked until the next period or until the budget is changed."
                    ),
                )
            return api_key, None, None
        finally:
            session.close()

    # --- forwarding --------------------------------------------------------------------
    async def forward(self, upstream: UpstreamRequest) -> Response:
        if self.adapter.name not in self.ident.allowed_providers:
            return await self.reject(
                403,
                "provider_not_allowed",
                f"This project is not configured to use {self.adapter.display_name}.",
                upstream.model,
            )
        api_key, code, message = await run_in_threadpool(self._load_key_sync)
        if api_key is None:
            status = {"budget_exceeded": 402, "provider_not_configured": 400}.get(code or "", 500)
            return await self.reject(status, code or "error", message or "error", upstream.model)

        headers = {
            "content-type": "application/json",
            **self.adapter.auth_headers(api_key),
            **upstream.headers,
        }
        client = get_http_client()
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            if upstream.stream:
                req = client.build_request("POST", upstream.url, json=upstream.body, headers=headers)
                resp = await client.send(req, stream=True)
            else:
                resp = await client.post(upstream.url, json=upstream.body, headers=headers)
        except httpx.TimeoutException:
            await self.record(
                model=upstream.model,
                streamed=upstream.stream,
                http_status=504,
                latency_ms=elapsed(),
                usage=Usage(),
                error_type="timeout",
                error_message="The provider did not respond in time.",
            )
            return JSONResponse(
                error_body("provider_timeout", "The provider did not respond in time."),
                status_code=504,
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            await self.record(
                model=upstream.model,
                streamed=upstream.stream,
                http_status=502,
                latency_ms=elapsed(),
                usage=Usage(),
                error_type="connection_error",
                error_message=type(exc).__name__,
            )
            return JSONResponse(
                error_body("provider_unreachable", "Could not connect to the provider."),
                status_code=502,
                headers=self._headers(),
            )

        if resp.status_code >= 400:
            content = await resp.aread()
            await resp.aclose()
            await self.record(
                model=upstream.model,
                streamed=upstream.stream,
                http_status=resp.status_code,
                latency_ms=elapsed(),
                usage=Usage(),
                error_type=classify_status(resp.status_code),
                error_message=extract_error_message(content),
            )
            return Response(
                content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
                headers=self._headers(resp),
            )

        if not upstream.stream:
            return await self._finish_buffered(resp, upstream, elapsed())
        return self._stream(resp, upstream, elapsed)

    async def _finish_buffered(self, resp: httpx.Response, upstream: UpstreamRequest, latency: int) -> Response:
        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except ValueError:
            await self.record(
                model=upstream.model,
                streamed=False,
                http_status=502,
                latency_ms=latency,
                usage=Usage(),
                error_type="invalid_response",
                error_message="The provider returned a non-JSON response.",
            )
            return JSONResponse(
                error_body("invalid_provider_response", "The provider returned an unexpected response."),
                status_code=502,
                headers=self._headers(),
            )
        usage = self.adapter.extract_usage(data)
        model = self.adapter.response_model(data) or upstream.model
        await self.record(model=model, streamed=False, http_status=resp.status_code, latency_ms=latency, usage=usage)
        return Response(
            resp.content,
            status_code=resp.status_code,
            media_type="application/json",
            headers=self._headers(resp),
        )

    def _stream(self, resp: httpx.Response, upstream: UpstreamRequest, elapsed) -> StreamingResponse:
        parser = self.adapter.stream_parser()

        async def body() -> AsyncIterator[bytes]:
            error_type: str | None = None
            error_message: str | None = None
            try:
                async for chunk in resp.aiter_bytes():  # decoded (handles gzip)
                    parser.feed(chunk)
                    yield chunk
            except httpx.HTTPError as exc:
                error_type, error_message = "stream_interrupted", type(exc).__name__
            except anyio.get_cancelled_exc_class():
                error_type, error_message = (
                    "client_disconnected",
                    "Client disconnected before the stream ended.",
                )
                raise
            finally:
                with anyio.CancelScope(shield=True):
                    await resp.aclose()
                if parser.error and not error_type:
                    error_type, error_message = "provider_error", parser.error
                await self.record(
                    model=parser.model or upstream.model,
                    streamed=True,
                    http_status=resp.status_code,
                    latency_ms=elapsed(),
                    usage=parser.usage,
                    error_type=error_type,
                    error_message=error_message,
                )

        return StreamingResponse(
            body(),
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "text/event-stream"),
            headers={**self._headers(resp), "cache-control": "no-cache", "x-accel-buffering": "no"},
        )
