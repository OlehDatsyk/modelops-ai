"""Provider adapter interface shared by OpenAI, Anthropic and Gemini."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.logging import redact


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class UpstreamRequest:
    url: str
    body: dict[str, Any]
    model: str
    stream: bool
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ValidationResult:
    status: str  # valid | invalid | error
    message: str
    models: list[str] = field(default_factory=list)


class StreamUsageParser(ABC):
    """Incrementally parses Server-Sent Events from a provider stream to capture usage."""

    def __init__(self) -> None:
        self.usage = Usage()
        self.model: str | None = None
        self.error: str | None = None
        self._buffer = b""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if isinstance(event, dict):
                self.handle_event(event)

    @abstractmethod
    def handle_event(self, event: dict[str, Any]) -> None: ...


def as_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def classify_status(status_code: int) -> str:
    if status_code in (401, 403):
        return "invalid_credentials"
    if status_code == 429:
        return "rate_limited"
    if status_code == 404:
        return "not_found"
    if status_code == 408:
        return "timeout"
    if 400 <= status_code < 500:
        return "bad_request"
    return "provider_error"


def extract_error_message(body: bytes | str | dict | None) -> str:
    """Pull a human-readable message out of a provider error body, redacted and truncated."""
    message = ""
    data: Any = body
    if isinstance(body, bytes | str):
        try:
            data = json.loads(body)
        except ValueError:
            message = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
            data = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("type") or "")
        elif isinstance(err, str):
            message = err
        elif "message" in data:
            message = str(data["message"])
    elif isinstance(data, list) and data and isinstance(data[0], dict):  # Gemini sometimes wraps in a list
        return extract_error_message(data[0])
    return redact(message.strip())[:480] or "Provider returned an error"


class ProviderAdapter(ABC):
    name: str
    display_name: str

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    def auth_headers(self, api_key: str) -> dict[str, str]: ...

    @abstractmethod
    async def validate_key(self, client: httpx.AsyncClient, api_key: str) -> ValidationResult: ...

    @abstractmethod
    def extract_usage(self, payload: dict[str, Any]) -> Usage: ...

    @abstractmethod
    def stream_parser(self) -> StreamUsageParser: ...

    def response_model(self, payload: dict[str, Any]) -> str | None:
        model = payload.get("model")
        return model if isinstance(model, str) and model else None

    async def _list_models(self, client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> tuple[int, Any]:
        response = await client.get(url, headers=headers, timeout=httpx.Timeout(15.0, connect=10.0))
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text

    def _validation_from_status(self, status: int, body: Any) -> ValidationResult:
        if status in (401, 403):
            return ValidationResult("invalid", "The provider rejected this API key: " + extract_error_message(body))
        if status == 429:
            return ValidationResult("error", "The provider rate-limited the validation request; try again later.")
        return ValidationResult("error", f"Unexpected response from provider (HTTP {status}).")
