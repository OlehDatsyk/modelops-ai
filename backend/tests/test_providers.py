"""Provider credential management and adapter unit tests (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.models import ProviderCredential
from app.providers.anthropic import AnthropicStreamParser
from app.providers.base import classify_status, extract_error_message
from app.providers.gemini import GeminiStreamParser
from app.providers.openai import OpenAIStreamParser

RAW_KEY = "sk-proj-SuperSecretValue1234567890"


@respx.mock
def test_store_and_validate_openai_key_encrypted_and_masked(client: TestClient, user, db):
    route = respx.get("https://api.openai.com/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-small"}, {"id": "gpt-4o-mini"}]}
        )
    )
    resp = client.put("/api/v1/providers/openai", json={"api_key": RAW_KEY}, headers=user["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "valid" and body["available_models"] == ["gpt-4o", "gpt-4o-mini"]
    assert body["key_hint"] == "sk-p…7890"
    assert RAW_KEY not in resp.text and RAW_KEY not in client.get("/api/v1/providers", headers=user["headers"]).text
    assert route.calls.last.request.headers["authorization"] == f"Bearer {RAW_KEY}"

    cred = db.scalar(select(ProviderCredential))
    assert RAW_KEY not in cred.encrypted_key and decrypt_secret(cred.encrypted_key) == RAW_KEY


@respx.mock
def test_invalid_anthropic_key_is_reported_not_faked(client: TestClient, user):
    respx.get(url__startswith="https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        )
    )
    body = client.put(
        "/api/v1/providers/anthropic", json={"api_key": "sk-ant-bad-key-000"}, headers=user["headers"]
    ).json()
    assert body["status"] == "invalid" and "invalid x-api-key" in body["status_message"]
    assert body["available_models"] == []


@respx.mock
def test_gemini_validation_filters_generate_models_and_handles_errors(client: TestClient, user):
    respx.get(url__startswith="https://generativelanguage.googleapis.com/v1beta/models").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-2.5-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                    ]
                },
            ),
            httpx.Response(
                400,
                json={
                    "error": {
                        "message": "API key not valid",
                        "status": "INVALID_ARGUMENT",
                        "details": [{"reason": "API_KEY_INVALID"}],
                    }
                },
            ),
            httpx.ConnectTimeout("slow"),
        ]
    )
    h = user["headers"]
    ok = client.put("/api/v1/providers/gemini", json={"api_key": "AIzaGoodKey123456"}, headers=h).json()
    assert ok["status"] == "valid" and ok["available_models"] == ["gemini-2.5-flash"]
    bad = client.post("/api/v1/providers/gemini/validate", headers=h).json()
    assert bad["status"] == "invalid"
    timeout = client.post("/api/v1/providers/gemini/validate", headers=h).json()
    assert timeout["status"] == "error" and "timed out" in timeout["status_message"]


def test_credential_validation_rules_and_delete(client: TestClient, user):
    h = user["headers"]
    assert client.put("/api/v1/providers/openai", json={"api_key": "short"}, headers=h).status_code == 422
    assert client.put("/api/v1/providers/openai", json={"api_key": "sk-has space-123"}, headers=h).status_code == 422
    assert client.put("/api/v1/providers/mistral", json={"api_key": "x" * 20}, headers=h).status_code == 422
    stored = client.put("/api/v1/providers/openai", json={"api_key": RAW_KEY, "validate_now": False}, headers=h).json()
    assert stored["status"] == "unverified"
    assert client.delete("/api/v1/providers/openai", headers=h).status_code == 204
    assert client.delete("/api/v1/providers/openai", headers=h).status_code == 404


def _sse(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def test_stream_parsers_handle_split_chunks():
    payload = _sse([{"model": "gpt-4o", "choices": []}, {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}])
    parser = OpenAIStreamParser()
    for i in range(0, len(payload), 7):  # feed in awkward 7-byte pieces
        parser.feed(payload[i : i + 7])
    assert (parser.usage.input_tokens, parser.usage.output_tokens, parser.model) == (3, 4, "gpt-4o")

    a = AnthropicStreamParser()
    a.feed(
        _sse(
            [
                {
                    "type": "message_start",
                    "message": {
                        "model": "claude",
                        "usage": {"input_tokens": 5, "cache_read_input_tokens": 5},
                    },
                },
                {"type": "message_delta", "usage": {"output_tokens": 9}},
                {"type": "error", "error": {"message": "overloaded"}},
            ]
        )
    )
    assert (a.usage.input_tokens, a.usage.output_tokens, a.error) == (10, 9, "overloaded")

    g = GeminiStreamParser()
    g.feed(b"data: not-json\n\n" + _sse([{"usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3}}]))
    assert (g.usage.input_tokens, g.usage.output_tokens) == (2, 3)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "invalid_credentials"),
        (403, "invalid_credentials"),
        (429, "rate_limited"),
        (404, "not_found"),
        (400, "bad_request"),
        (500, "provider_error"),
        (529, "provider_error"),
    ],
)
def test_classify_status(status, expected):
    assert classify_status(status) == expected


def test_extract_error_message_redacts_and_truncates():
    msg = extract_error_message(json.dumps({"error": {"message": "bad key sk-live-ABCDEFGHIJKLMNOP " + "x" * 1000}}))
    assert "sk-live-ABCDEFGHIJKLMNOP" not in msg and len(msg) <= 480
    assert extract_error_message(b"<html>gateway</html>") == "<html>gateway</html>"
    assert extract_error_message(b"") == "Provider returned an error"
