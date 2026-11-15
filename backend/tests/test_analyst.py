"""AI Analyst: configuration handling, no-data behaviour, tool loop (mocked LLM) and tool safety."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.providers.base import Usage
from app.services.analyst_tools import ToolContext, run_tool
from app.services.usage import RequestRecord, record_request


@pytest.fixture
def analyst_openai(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_analyst_provider", "openai")
    monkeypatch.setattr(settings, "ai_analyst_model", "gpt-4.1-mini")
    monkeypatch.setattr(settings, "ai_analyst_api_key", "sk-analyst-test-key-123456")


def _seed(db, user_id: str, model="gpt-4o", inp=1_000_000):
    record_request(
        db,
        RequestRecord(
            "req_" + uuid.uuid4().hex[:16],
            uuid.UUID(user_id),
            None,
            None,
            "openai",
            model,
            "chat",
            False,
            200,
            120,
            Usage(inp, 1000),
        ),
    )


def test_status_and_not_configured(client: TestClient, user, db):
    assert client.get("/api/v1/analyst/status", headers=user["headers"]).json()["configured"] is False
    _seed(db, user["user_id"])
    resp = client.post(
        "/api/v1/analyst/ask", json={"question": "Which model is most expensive?"}, headers=user["headers"]
    )
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "analyst_not_configured"


def test_no_data_answer_is_explicit(client: TestClient, user, analyst_openai):
    with respx.mock(assert_all_called=False) as mock:
        llm = mock.post("https://api.openai.com/v1/chat/completions")
        resp = client.post(
            "/api/v1/analyst/ask",
            json={"question": "How much did I spend yesterday?"},
            headers=user["headers"],
        )
        assert not llm.called  # no paid call when there is nothing to analyse
    assert resp.status_code == 200 and "no request data" in resp.json()["answer"]["content"]


@respx.mock
def test_openai_tool_loop_uses_real_metrics(client: TestClient, user, db, analyst_openai):
    _seed(db, user["user_id"], "gpt-4o")
    _seed(db, user["user_id"], "gpt-4o-mini")
    replies = [
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_breakdown",
                                        "arguments": json.dumps({"dimension": "model", "period": "last_7_days"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "gpt-4o is your most expensive model (estimate).",
                        }
                    }
                ]
            },
        ),
    ]
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=replies)
    resp = client.post(
        "/api/v1/analyst/ask",
        json={"question": "Which model is the most expensive?"},
        headers=user["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "gpt-4o" in data["answer"]["content"]
    evidence = data["answer"]["tool_results"][0]
    assert evidence["tool"] == "get_breakdown" and evidence["result"]["rows"][0]["model"] == "gpt-4o"

    second_request = json.loads(route.calls[1].request.content)
    tool_msg = second_request["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1" and "gpt-4o" in tool_msg["content"]
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-analyst-test-key-123456"

    conv_id = data["conversation"]["id"]
    detail = client.get(f"/api/v1/analyst/conversations/{conv_id}", headers=user["headers"]).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


@respx.mock
def test_anthropic_tool_loop(client: TestClient, user, db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_analyst_provider", "anthropic")
    monkeypatch.setattr(settings, "ai_analyst_model", "claude-haiku-4-5")
    monkeypatch.setattr(settings, "ai_analyst_api_key", "sk-ant-analyst-123456")
    _seed(db, user["user_id"])
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "get_spend_summary",
                            "input": {"period": "today"},
                        }
                    ],
                    "stop_reason": "tool_use",
                },
            ),
            httpx.Response(200, json={"content": [{"type": "text", "text": "You spent about $2.52 today."}]}),
        ]
    )
    resp = client.post("/api/v1/analyst/ask", json={"question": "How much did I spend today?"}, headers=user["headers"])
    assert resp.status_code == 200 and "$2.52" in resp.json()["answer"]["content"]
    follow_up = json.loads(route.calls[1].request.content)
    assert follow_up["messages"][-1]["content"][0]["type"] == "tool_result"
    assert route.calls[0].request.headers["x-api-key"] == "sk-ant-analyst-123456"


@respx.mock
def test_analyst_provider_error_is_sanitised(client: TestClient, user, db, analyst_openai):
    _seed(db, user["user_id"])
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "upstream exploded"}})
    )
    resp = client.post("/api/v1/analyst/ask", json={"question": "Why?"}, headers=user["headers"])
    assert resp.status_code == 502 and resp.json()["error"]["code"] == "analyst_provider_error"


def test_tools_are_scoped_validated_and_cannot_be_redirected(client: TestClient, user, other_user, db):
    _seed(db, user["user_id"])
    ctx_other = ToolContext(db, uuid.UUID(other_user["user_id"]))
    # Bob's context never sees Alice's data, even when asking for "all" data.
    assert run_tool(ctx_other, "get_spend_summary", {"period": "last_30_days"})["current"]["total_requests"] == 0
    # Unknown tools and bad arguments are rejected without raising.
    assert "error" in run_tool(ctx_other, "run_sql", {"query": "select * from users"})
    assert "error" in run_tool(ctx_other, "get_daily_spend", {"days": 10_000})
    assert "error" in run_tool(ctx_other, "get_breakdown", {"dimension": "user_id"})
    # Project names are resolved within the caller's account only.
    from tests.conftest import create_project

    create_project(client, user["headers"], "Alice Secret Project")
    assert (
        "No project named"
        in run_tool(ctx_other, "get_spend_summary", {"period": "today", "project_name": "Alice Secret Project"})[
            "error"
        ]
    )
    ctx_alice = ToolContext(db, uuid.UUID(user["user_id"]))
    for name, args in [
        ("compare_periods", {"days": 7}),
        ("get_daily_spend", {"days": 3}),
        ("get_error_analysis", {}),
        ("get_optimisation_signals", {}),
    ]:
        assert "error" not in run_tool(ctx_alice, name, args), name
    signals = run_tool(ctx_alice, "get_optimisation_signals", {})["models"][0]
    assert signals["model"] == "openai/gpt-4o" and signals["cheaper_same_provider_models"]
