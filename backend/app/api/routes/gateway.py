"""Provider-compatible gateway endpoints authenticated with project API keys."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from app.api.deps import GatewayIdentity, get_gateway_identity
from app.providers.gemini import MODEL_NAME_RE
from app.providers.registry import anthropic_adapter, gemini_adapter, openai_adapter
from app.schemas.gateway import (
    AnthropicMessagesRequest,
    GeminiGenerateRequest,
    GeminiNativeRequest,
    OpenAIChatRequest,
)
from app.services.gateway import GatewayCall

router = APIRouter(prefix="/gateway", tags=["gateway"])


async def _parse(
    call: GatewayCall, request: Request, schema: type[BaseModel]
) -> tuple[dict[str, Any] | None, Response | None]:
    raw = await request.body()
    try:
        payload = json.loads(raw or b"null")
    except ValueError:
        return None, await call.reject(400, "invalid_request", "Request body must be valid JSON.")
    if not isinstance(payload, dict):
        return None, await call.reject(400, "invalid_request", "Request body must be a JSON object.")
    try:
        schema.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        model = payload.get("model") if isinstance(payload.get("model"), str) else ""
        return None, await call.reject(
            400, "invalid_request", f"Invalid field '{loc}': {first.get('msg')}", model[:120]
        )
    return payload, None


@router.post("/openai/chat/completions", summary="OpenAI Chat Completions (OpenAI-compatible)")
@router.post("/openai/v1/chat/completions", include_in_schema=False)
async def openai_chat_completions(
    request: Request, background: BackgroundTasks, ident: GatewayIdentity = Depends(get_gateway_identity)
):
    adapter = openai_adapter()
    call = GatewayCall(request, background, ident, adapter, "chat.completions")
    payload, error = await _parse(call, request, OpenAIChatRequest)
    if error:
        return error
    return await call.forward(adapter.chat_completions(payload))


@router.post("/anthropic/messages", summary="Anthropic Messages (Anthropic-compatible)")
@router.post("/anthropic/v1/messages", include_in_schema=False)
async def anthropic_messages(
    request: Request, background: BackgroundTasks, ident: GatewayIdentity = Depends(get_gateway_identity)
):
    adapter = anthropic_adapter()
    call = GatewayCall(request, background, ident, adapter, "messages")
    payload, error = await _parse(call, request, AnthropicMessagesRequest)
    if error:
        return error
    beta = request.headers.get("anthropic-beta")
    return await call.forward(adapter.messages(payload, beta_header=beta[:200] if beta else None))


@router.post("/gemini/generate", summary="Gemini generateContent (model in body, optional stream flag)")
async def gemini_generate(
    request: Request, background: BackgroundTasks, ident: GatewayIdentity = Depends(get_gateway_identity)
):
    adapter = gemini_adapter()
    call = GatewayCall(request, background, ident, adapter, "generateContent")
    payload, error = await _parse(call, request, GeminiGenerateRequest)
    if error:
        return error
    model = str(payload.pop("model"))
    stream = bool(payload.pop("stream", False))
    if stream:
        call.endpoint = "streamGenerateContent"
    return await call.forward(adapter.generate(model, payload, stream))


@router.post(
    "/gemini/v1beta/models/{model_action}",
    summary="Gemini native path, e.g. models/gemini-2.5-flash:generateContent",
)
async def gemini_native(
    model_action: str,
    request: Request,
    background: BackgroundTasks,
    ident: GatewayIdentity = Depends(get_gateway_identity),
):
    adapter = gemini_adapter()
    model, _, action = model_action.partition(":")
    call = GatewayCall(request, background, ident, adapter, action or "unknown")
    if action not in ("generateContent", "streamGenerateContent") or not MODEL_NAME_RE.match(model):
        return await call.reject(
            404,
            "unsupported_endpoint",
            "Supported: models/{model}:generateContent and :streamGenerateContent",
        )
    payload, error = await _parse(call, request, GeminiNativeRequest)
    if error:
        return error
    return await call.forward(adapter.generate(model, payload, stream=action == "streamGenerateContent"))
