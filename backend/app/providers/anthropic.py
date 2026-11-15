"""Anthropic adapter (Messages API)."""

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


def _input_tokens(usage: dict[str, Any]) -> int:
    # Prompt-caching tokens are billed as input at different rates; they are counted as input here
    # (see PROJECT_REVIEW.md "Known limitations").
    return (
        as_int(usage.get("input_tokens"))
        + as_int(usage.get("cache_creation_input_tokens"))
        + as_int(usage.get("cache_read_input_tokens"))
    )


class AnthropicStreamParser(StreamUsageParser):
    def handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "message_start":
            message = event.get("message") or {}
            if isinstance(message.get("model"), str):
                self.model = message["model"]
            usage = message.get("usage") or {}
            self.usage = Usage(_input_tokens(usage), as_int(usage.get("output_tokens")))
        elif kind == "message_delta":
            usage = event.get("usage") or {}
            if "output_tokens" in usage:  # cumulative count
                self.usage.output_tokens = as_int(usage.get("output_tokens"))
            if usage.get("input_tokens") is not None:
                self.usage.input_tokens = max(self.usage.input_tokens, _input_tokens(usage))
        elif kind == "error":
            err = event.get("error") or {}
            self.error = str(err.get("message", "stream error"))[:480]


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"
    display_name = "Anthropic Claude"

    def __init__(self, base_url: str, api_version: str):
        super().__init__(base_url)
        self.api_version = api_version

    def auth_headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": self.api_version}

    def messages(self, payload: dict[str, Any], beta_header: str | None = None) -> UpstreamRequest:
        headers = {"anthropic-beta": beta_header} if beta_header else {}
        return UpstreamRequest(
            url=f"{self.base_url}/v1/messages",
            body=dict(payload),
            model=str(payload["model"]),
            stream=bool(payload.get("stream")),
            headers=headers,
        )

    def extract_usage(self, payload: dict[str, Any]) -> Usage:
        usage = payload.get("usage") or {}
        return Usage(_input_tokens(usage), as_int(usage.get("output_tokens")))

    def stream_parser(self) -> StreamUsageParser:
        return AnthropicStreamParser()

    async def validate_key(self, client: httpx.AsyncClient, api_key: str) -> ValidationResult:
        status, body = await self._list_models(
            client, f"{self.base_url}/v1/models?limit=1000", self.auth_headers(api_key)
        )
        if status == 200 and isinstance(body, dict):
            ids = sorted(m["id"] for m in body.get("data", []) if isinstance(m, dict) and isinstance(m.get("id"), str))
            return ValidationResult("valid", f"Key accepted. {len(ids)} models available.", ids[:300])
        return self._validation_from_status(status, body)
