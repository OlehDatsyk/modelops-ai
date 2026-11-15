"""Minimal structural validation of gateway payloads.

Only the fields the gateway relies on are validated; everything else is forwarded unchanged
(``extra="allow"``) so new provider parameters keep working without a gateway release.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Passthrough(BaseModel):
    model_config = ConfigDict(extra="allow")


class OpenAIChatRequest(_Passthrough):
    model: str = Field(min_length=1, max_length=120)
    messages: list[dict] = Field(min_length=1)
    stream: bool | None = None


class AnthropicMessagesRequest(_Passthrough):
    model: str = Field(min_length=1, max_length=120)
    messages: list[dict] = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    stream: bool | None = None


class GeminiGenerateRequest(_Passthrough):
    model: str = Field(min_length=1, max_length=120, pattern=r"^(models/)?[A-Za-z0-9][A-Za-z0-9._\-]*$")
    contents: list[dict] = Field(min_length=1)
    stream: bool = False


class GeminiNativeRequest(_Passthrough):
    contents: list[dict] = Field(min_length=1)
