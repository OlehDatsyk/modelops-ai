"""OpenAI adapter (Chat Completions API)."""

from __future__ import annotations

from typing import Any

import httpx

from app.providers.base import (
    ProviderAdapter,
    StreamUsageParser,
    UpstreamRequest,
    Usage,
    ValidationResult,
    as_int,
)

_NON_CHAT_HINTS = ("embedding", "whisper", "tts", "dall-e", "moderation", "davinci", "babbage", "transcribe")


class OpenAIStreamParser(StreamUsageParser):
    def handle_event(self, event: dict[str, Any]) -> None:
        if isinstance(event.get("model"), str):
            self.model = event["model"]
        usage = event.get("usage")
        if isinstance(usage, dict):  # sent in the final chunk when stream_options.include_usage is true
            self.usage = Usage(as_int(usage.get("prompt_tokens")), as_int(usage.get("completion_tokens")))
        if isinstance(event.get("error"), dict):
            self.error = str(event["error"].get("message", "stream error"))[:480]


class OpenAIAdapter(ProviderAdapter):
    name = "openai"
    display_name = "OpenAI"

    def auth_headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def chat_completions(self, payload: dict[str, Any]) -> UpstreamRequest:
        body = dict(payload)
        stream = bool(body.get("stream"))
        if stream:
            # Ask OpenAI to include token usage in the final stream chunk so it can be recorded.
            options = dict(body.get("stream_options") or {})
            options.setdefault("include_usage", True)
            body["stream_options"] = options
        return UpstreamRequest(
            url=f"{self.base_url}/v1/chat/completions", body=body, model=str(body["model"]), stream=stream
        )

    def extract_usage(self, payload: dict[str, Any]) -> Usage:
        usage = payload.get("usage") or {}
        return Usage(as_int(usage.get("prompt_tokens")), as_int(usage.get("completion_tokens")))

    def stream_parser(self) -> StreamUsageParser:
        return OpenAIStreamParser()

    async def validate_key(self, client: httpx.AsyncClient, api_key: str) -> ValidationResult:
        status, body = await self._list_models(client, f"{self.base_url}/v1/models", self.auth_headers(api_key))
        if status == 200 and isinstance(body, dict):
            ids = sorted(
                m["id"]
                for m in body.get("data", [])
                if isinstance(m, dict)
                and isinstance(m.get("id"), str)
                and not any(h in m["id"] for h in _NON_CHAT_HINTS)
            )
            return ValidationResult("valid", f"Key accepted. {len(ids)} chat-capable models available.", ids[:300])
        return self._validation_from_status(status, body)
