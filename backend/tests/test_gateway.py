"""Gateway integration tests with mocked provider APIs (respx)."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import ApiRequest, Notification, ProviderCredential, UsageDaily

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_STREAM_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent"

CHAT = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}]}


def _requests(db) -> list[ApiRequest]:
    db.expire_all()
    return db.scalars(select(ApiRequest).order_by(ApiRequest.created_at)).all()


@respx.mock
def test_openai_success_records_usage_cost_and_returns_provider_body(client: TestClient, gateway_setup, db):
    route = respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi!"}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            },
        )
    )
    resp = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["gw"])
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Hi!"
    assert resp.headers["x-modelops-request-id"].startswith("req_")

    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-openai-secret-value-abcdef"
    assert json.loads(sent.content)["messages"][0]["content"] == "Hello"

    (row,) = _requests(db)
    assert row.status == "success" and row.provider == "openai"
    assert row.model == "gpt-4o-mini-2024-07-18"  # dated variant priced via the gpt-4o-mini entry
    assert (row.input_tokens, row.output_tokens, row.total_tokens) == (1000, 500, 1500)
    assert row.pricing_model_key == "gpt-4o-mini"
    # 1000 * 0.15/1M + 500 * 0.60/1M = 0.00015 + 0.0003
    assert row.cost_total_usd == Decimal("0.00045000") and row.cost_status == "estimated"
    assert row.request_id == resp.headers["x-modelops-request-id"]
    daily = db.scalars(select(UsageDaily)).all()
    assert len(daily) == 1 and daily[0].request_count == 1 and daily[0].cost_usd == Decimal("0.00045")


@respx.mock
def test_openai_streaming_injects_include_usage_and_captures_tokens(client: TestClient, gateway_setup, db):
    chunks = [
        {"id": "c", "model": "gpt-4o", "choices": [{"delta": {"content": "Hel"}}]},
        {"id": "c", "model": "gpt-4o", "choices": [{"delta": {"content": "lo"}}]},
        {"id": "c", "model": "gpt-4o", "choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 7}},
    ]
    sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    route = respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
    )
    body = {**CHAT, "model": "gpt-4o", "stream": True}
    with client.stream("POST", "/api/v1/gateway/openai/chat/completions", json=body, headers=gateway_setup["gw"]) as r:
        received = b"".join(r.iter_raw())
    assert b"[DONE]" in received and b"Hel" in received
    assert json.loads(route.calls.last.request.content)["stream_options"] == {"include_usage": True}
    (row,) = _requests(db)
    assert row.streamed and row.status == "success"
    assert (row.input_tokens, row.output_tokens) == (12, 7)


@respx.mock
def test_anthropic_messages_success_and_headers(client: TestClient, gateway_setup, db):
    route = respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "model": "claude-sonnet-4-5-20250929",
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {"input_tokens": 2000, "output_tokens": 100, "cache_read_input_tokens": 0},
            },
        )
    )
    body = {"model": "claude-sonnet-4-5", "max_tokens": 256, "messages": [{"role": "user", "content": "Hi"}]}
    resp = client.post("/api/v1/gateway/anthropic/v1/messages", json=body, headers={"x-api-key": gateway_setup["key"]})
    assert resp.status_code == 200 and resp.json()["content"][0]["text"] == "Hello"
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "sk-anthropic-secret-value-abcdef"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    (row,) = _requests(db)
    # 2000 * 3/1M + 100 * 15/1M = 0.006 + 0.0015
    assert row.cost_total_usd == Decimal("0.00750000") and row.pricing_model_key == "claude-sonnet-4-5"


@respx.mock
def test_anthropic_streaming_usage(client: TestClient, gateway_setup, db):
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {"model": "claude-haiku-4-5", "usage": {"input_tokens": 30, "output_tokens": 1}},
            },
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
        ),
        ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 42}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    sse = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)
    respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
    )
    body = {
        "model": "claude-haiku-4-5",
        "max_tokens": 64,
        "stream": True,
        "messages": [{"role": "user", "content": "x"}],
    }
    with client.stream("POST", "/api/v1/gateway/anthropic/messages", json=body, headers=gateway_setup["gw"]) as r:
        assert b"message_stop" in b"".join(r.iter_raw())
    (row,) = _requests(db)
    assert (row.input_tokens, row.output_tokens) == (30, 42) and row.streamed


@respx.mock
def test_gemini_generate_and_native_path(client: TestClient, gateway_setup, db):
    route = respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Hi"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 40,
                    "thoughtsTokenCount": 10,
                },
                "modelVersion": "gemini-2.5-flash",
            },
        )
    )
    body = {"model": "gemini-2.5-flash", "contents": [{"role": "user", "parts": [{"text": "Hi"}]}]}
    resp = client.post("/api/v1/gateway/gemini/generate", json=body, headers=gateway_setup["gw"])
    assert resp.status_code == 200
    sent = route.calls.last.request
    assert sent.headers["x-goog-api-key"] == "sk-gemini-secret-value-abcdef"
    assert "model" not in json.loads(sent.content)  # model goes in the URL, not the body

    native = client.post(
        "/api/v1/gateway/gemini/v1beta/models/gemini-2.5-flash:generateContent",
        json={"contents": body["contents"]},
        headers={"x-goog-api-key": gateway_setup["key"]},
    )
    assert native.status_code == 200
    rows = _requests(db)
    assert len(rows) == 2 and all(r.output_tokens == 50 and r.input_tokens == 100 for r in rows)


@respx.mock
def test_gemini_streaming_usage(client: TestClient, gateway_setup, db):
    chunks = [
        {"candidates": [{"content": {"parts": [{"text": "A"}]}}], "usageMetadata": {"promptTokenCount": 9}},
        {
            "candidates": [{"content": {"parts": [{"text": "B"}]}}],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 21},
        },
    ]
    sse = "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks)
    route = respx.post(url__startswith=GEMINI_STREAM_URL).mock(
        return_value=httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
    )
    body = {"model": "gemini-2.5-flash", "stream": True, "contents": [{"parts": [{"text": "x"}]}]}
    with client.stream("POST", "/api/v1/gateway/gemini/generate", json=body, headers=gateway_setup["gw"]) as r:
        b"".join(r.iter_raw())
    assert route.calls.last.request.url.params["alt"] == "sse"
    (row,) = _requests(db)
    assert (row.input_tokens, row.output_tokens) == (9, 21) and row.endpoint == "streamGenerateContent"


def test_gateway_rejects_missing_invalid_and_revoked_keys(client: TestClient, gateway_setup):
    assert client.post("/api/v1/gateway/openai/chat/completions", json=CHAT).status_code == 401
    bad = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers={"Authorization": "Bearer mk_nope"})
    assert bad.status_code == 401
    jwt_instead = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["headers"])
    assert jwt_instead.status_code == 401  # user access tokens are not gateway keys

    project_id = gateway_setup["project"]["id"]
    keys = client.get(f"/api/v1/projects/{project_id}/keys", headers=gateway_setup["headers"]).json()
    client.post(f"/api/v1/projects/{project_id}/keys/{keys[0]['id']}/revoke", headers=gateway_setup["headers"])
    revoked = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["gw"])
    assert revoked.status_code == 401


def test_malformed_requests_are_rejected_and_recorded(client: TestClient, gateway_setup, db):
    not_json = client.post(
        "/api/v1/gateway/openai/chat/completions",
        content=b"{not json",
        headers={**gateway_setup["gw"], "content-type": "application/json"},
    )
    assert not_json.status_code == 400 and not_json.json()["error"]["code"] == "invalid_request"
    missing = client.post(
        "/api/v1/gateway/openai/chat/completions", json={"model": "gpt-4o"}, headers=gateway_setup["gw"]
    )
    assert missing.status_code == 400 and "messages" in missing.json()["error"]["message"]
    no_max = client.post(
        "/api/v1/gateway/anthropic/messages",
        json={"model": "claude-haiku-4-5", "messages": [{"role": "user", "content": "x"}]},
        headers=gateway_setup["gw"],
    )
    assert no_max.status_code == 400
    rows = _requests(db)
    assert len(rows) == 3 and all(r.status == "error" and r.error_type == "invalid_request" for r in rows)


def test_provider_not_allowed_for_project(client: TestClient, user, db):
    from tests.conftest import add_credential, create_key, create_project

    project = create_project(client, user["headers"], name="OpenAI only", providers=["openai"])
    key = create_key(client, user["headers"], project["id"])
    add_credential(client, user["headers"], "anthropic")
    resp = client.post(
        "/api/v1/gateway/anthropic/messages",
        json={"model": "claude-haiku-4-5", "max_tokens": 5, "messages": [{"role": "user", "content": "x"}]},
        headers={"x-api-key": key},
    )
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "provider_not_allowed"


def test_provider_not_configured(client: TestClient, user):
    from tests.conftest import create_key, create_project

    project = create_project(client, user["headers"])
    key = create_key(client, user["headers"], project["id"])
    resp = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "provider_not_configured"


@respx.mock
def test_upstream_invalid_key_marks_credential_invalid(client: TestClient, gateway_setup, db):
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "Incorrect API key provided: sk-open*****cdef"}})
    )
    resp = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["gw"])
    assert resp.status_code == 401
    (row,) = _requests(db)
    assert row.error_type == "invalid_credentials" and row.status == "error"
    cred = db.scalar(select(ProviderCredential).where(ProviderCredential.provider == "openai"))
    db.refresh(cred)
    assert cred.status == "invalid"


@respx.mock
def test_upstream_rate_limit_passes_retry_after(client: TestClient, gateway_setup, db):
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "Rate limit reached"}}, headers={"retry-after": "7"}
        )
    )
    resp = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["gw"])
    assert resp.status_code == 429 and resp.headers["retry-after"] == "7"
    (row,) = _requests(db)
    assert row.error_type == "rate_limited" and row.error_message == "Rate limit reached"


@respx.mock
@pytest.mark.parametrize(
    ("exc", "status", "error_type"),
    [(httpx.ReadTimeout("slow"), 504, "timeout"), (httpx.ConnectError("refused"), 502, "connection_error")],
)
def test_timeouts_and_connection_errors(client: TestClient, gateway_setup, db, exc, status, error_type):
    respx.post(OPENAI_URL).mock(side_effect=exc)
    resp = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["gw"])
    assert resp.status_code == status
    (row,) = _requests(db)
    assert row.error_type == error_type and row.http_status == status


@respx.mock
def test_unknown_model_cost_is_unknown_not_zero(client: TestClient, gateway_setup, db):
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(
            200, json={"model": "brand-new-model", "usage": {"prompt_tokens": 5, "completion_tokens": 5}}
        )
    )
    client.post(
        "/api/v1/gateway/openai/chat/completions",
        json={**CHAT, "model": "brand-new-model"},
        headers=gateway_setup["gw"],
    )
    (row,) = _requests(db)
    assert row.cost_status == "unknown" and row.cost_total_usd is None


@respx.mock
def test_enforced_budget_blocks_requests(client: TestClient, gateway_setup, db):
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(
            200, json={"model": "gpt-4o", "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}
        )
    )
    budget = client.post(
        "/api/v1/budgets",
        json={"name": "Daily cap", "period": "daily", "limit_usd": "1.00", "enforce_limit": True},
        headers=gateway_setup["headers"],
    )
    assert budget.status_code == 201
    first = client.post(
        "/api/v1/gateway/openai/chat/completions",
        json={**CHAT, "model": "gpt-4o"},
        headers=gateway_setup["gw"],
    )
    assert first.status_code == 200  # $2.50 spent, limit now exceeded
    blocked = client.post("/api/v1/gateway/openai/chat/completions", json=CHAT, headers=gateway_setup["gw"])
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "budget_exceeded"
    db.expire_all()
    notes = db.scalars(select(Notification).where(Notification.kind == "budget")).all()
    assert len(notes) == 1 and notes[0].severity == "critical"  # one notification for the 100% threshold


@respx.mock
def test_prompt_content_is_not_stored(client: TestClient, gateway_setup, db):
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o",
                "choices": [{"message": {"content": "TOP-SECRET-ANSWER"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
    )
    client.post(
        "/api/v1/gateway/openai/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "TOP-SECRET-PROMPT"}]},
        headers=gateway_setup["gw"],
    )
    (row,) = _requests(db)
    dumped = json.dumps({c.name: str(getattr(row, c.name)) for c in ApiRequest.__table__.columns})
    assert "TOP-SECRET" not in dumped


@respx.mock
def test_gzip_compressed_stream_is_decoded_for_client_and_usage(client: TestClient, gateway_setup, db):
    import gzip

    sse = (
        'data: {"model": "gpt-4o", "choices": [{"delta": {"content": "Hi"}}]}\n\n'
        'data: {"model": "gpt-4o", "choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(
            200,
            content=gzip.compress(sse.encode()),
            headers={"content-type": "text/event-stream", "content-encoding": "gzip"},
        )
    )
    body = {**CHAT, "model": "gpt-4o", "stream": True}
    with client.stream("POST", "/api/v1/gateway/openai/chat/completions", json=body, headers=gateway_setup["gw"]) as r:
        received = b"".join(r.iter_raw())
    assert b"[DONE]" in received  # plain text, not gzip bytes
    (row,) = _requests(db)
    assert (row.input_tokens, row.output_tokens) == (4, 2)
