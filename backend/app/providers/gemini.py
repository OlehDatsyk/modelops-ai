"""Google Gemini adapter (Generative Language API, generateContent)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from app.providers.base import (
    ProviderAdapter,
    StreamUsageParser,
    UpstreamRequest,
    Usage,
    ValidationResult,
    as_int,
)

MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,119}$")


def _usage(meta: dict[str, Any]) -> Usage:
    # Thinking tokens are billed as output tokens.
    return Usage(
        as_int(meta.get("promptTokenCount")),
        as_int(meta.get("candidatesTokenCount")) + as_int(meta.get("thoughtsTokenCount")),
    )


class GeminiStreamParser(StreamUsageParser):
    def handle_event(self, event: dict[str, Any]) -> None:
        meta = event.get("usageMetadata")
        if isinstance(meta, dict):  # each chunk carries running totals; keep the latest
            self.usage = _usage(meta)
        if isinstance(event.get("modelVersion"), str):
            self.model = event["modelVersion"]
        if isinstance(event.get("error"), dict):
            self.error = str(event["error"].get("message", "stream error"))[:480]


class GeminiAdapter(ProviderAdapter):
    name = "gemini"
    display_name = "Google Gemini"

    def auth_headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key}

    def generate(self, model: str, payload: dict[str, Any], stream: bool) -> UpstreamRequest:
        model = model.removeprefix("models/")
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return UpstreamRequest(
            url=f"{self.base_url}/v1beta/models/{quote(model, safe='.-_')}:{action}",
            body=dict(payload),
            model=model,
            stream=stream,
        )

    def extract_usage(self, payload: dict[str, Any]) -> Usage:
        return _usage(payload.get("usageMetadata") or {})

    def response_model(self, payload: dict[str, Any]) -> str | None:
        version = payload.get("modelVersion")
        return version if isinstance(version, str) and version else None

    def stream_parser(self) -> StreamUsageParser:
        return GeminiStreamParser()

    async def validate_key(self, client: httpx.AsyncClient, api_key: str) -> ValidationResult:
        status, body = await self._list_models(
            client, f"{self.base_url}/v1beta/models?pageSize=1000", self.auth_headers(api_key)
        )
        if status == 200 and isinstance(body, dict):
            ids = sorted(
                m["name"].removeprefix("models/")
                for m in body.get("models", [])
                if isinstance(m, dict)
                and isinstance(m.get("name"), str)
                and "generateContent" in (m.get("supportedGenerationMethods") or [])
            )
            return ValidationResult("valid", f"Key accepted. {len(ids)} generateContent models available.", ids[:300])
        # Gemini answers 400 API_KEY_INVALID for bad keys.
        if status == 400 and "API_KEY_INVALID" in str(body):
            return ValidationResult("invalid", "The provider rejected this API key (API_KEY_INVALID).")
        return self._validation_from_status(status, body)
