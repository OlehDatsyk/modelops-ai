"""Adapter registry and the shared outbound HTTP client."""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.providers.anthropic import AnthropicAdapter
from app.providers.base import ProviderAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.openai import OpenAIAdapter

_client: httpx.AsyncClient | None = None


def openai_adapter() -> OpenAIAdapter:
    return OpenAIAdapter(get_settings().openai_base_url)


def anthropic_adapter() -> AnthropicAdapter:
    settings = get_settings()
    return AnthropicAdapter(settings.anthropic_base_url, settings.anthropic_version)


def gemini_adapter() -> GeminiAdapter:
    return GeminiAdapter(get_settings().gemini_base_url)


def get_adapter(provider: str) -> ProviderAdapter:
    factories = {"openai": openai_adapter, "anthropic": anthropic_adapter, "gemini": gemini_adapter}
    if provider not in factories:
        raise ValueError(f"Unknown provider: {provider}")
    return factories[provider]()


def get_http_client() -> httpx.AsyncClient:
    """Process-wide AsyncClient (connection pooling). Created lazily, closed on shutdown."""
    global _client
    if _client is None or _client.is_closed:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.provider_timeout_seconds, connect=settings.provider_connect_timeout_seconds),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            follow_redirects=False,
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
