"""Analytics, request-log and cost-summary tests using records inserted through the real recorder."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update

from app.db.base import utcnow
from app.models import ApiRequest
from app.providers.base import Usage
from app.services.usage import RequestRecord, record_request
from tests.conftest import create_project


def _record(db, user_id, project_id, provider, model, inp, out, status=200, error=None, latency=100, ago=None):
    rid = "req_" + uuid.uuid4().hex[:20]
    record_request(
        db,
        RequestRecord(
            rid,
            uuid.UUID(user_id),
            uuid.UUID(project_id) if project_id else None,
            None,
            provider,
            model,
            "chat",
            False,
            status,
            latency,
            Usage(inp, out),
            error_type=error,
            error_message="boom" if error else None,
        ),
    )
    if ago is not None:
        db.execute(update(ApiRequest).where(ApiRequest.request_id == rid).values(created_at=utcnow() - ago))
        db.commit()
    return rid


def test_empty_account_returns_zeroes_not_fake_data(client: TestClient, user):
    data = client.get("/api/v1/analytics/overview?range=7d", headers=user["headers"]).json()
    cur = data["summary"]["current"]
    assert cur["total_requests"] == 0 and cur["estimated_cost_usd"] == 0 and cur["avg_latency_ms"] is None
    assert data["by_provider"] == [] and data["by_model"] == []
    assert len(data["timeseries"]) == 7 or len(data["timeseries"]) == 8
    assert all(p["requests"] == 0 for p in data["timeseries"])


def test_overview_aggregates(client: TestClient, user, db):
    p = create_project(client, user["headers"], "Chat App")
    uid = user["user_id"]
    _record(db, uid, p["id"], "openai", "gpt-4o", 1_000_000, 0, latency=200)  # $2.50
    _record(db, uid, p["id"], "openai", "gpt-4o-mini", 1_000_000, 1_000_000, latency=100)  # $0.75
    _record(db, uid, None, "anthropic", "claude-haiku-4-5", 0, 0, status=500, error="provider_error", latency=300)
    _record(db, uid, p["id"], "gemini", "gemini-2.5-flash", 10, 10, ago=timedelta(days=10))  # outside 7d

    data = client.get("/api/v1/analytics/overview?range=7d", headers=user["headers"]).json()
    cur = data["summary"]["current"]
    assert cur["total_requests"] == 3 and cur["successful_requests"] == 2 and cur["failed_requests"] == 1
    assert cur["input_tokens"] == 2_000_000 and cur["output_tokens"] == 1_000_000
    assert abs(cur["estimated_cost_usd"] - 3.25) < 1e-9
    assert cur["avg_latency_ms"] == 200.0 and cur["error_rate"] == 33.33
    assert data["summary"]["previous"]["total_requests"] == 1

    providers = {r["provider"]: r for r in data["by_provider"]}
    assert providers["openai"]["requests"] == 2 and providers["anthropic"]["error_rate"] == 100.0
    assert data["by_model"][0]["model"] == "gpt-4o"  # ordered by cost
    projects = {r["project_name"]: r for r in data["by_project"]}
    assert projects["Chat App"]["requests"] == 2 and projects["(no project)"]["requests"] == 1
    assert sum(b["requests"] for b in data["timeseries"]) == 3

    filtered = client.get(f"/api/v1/analytics/overview?range=30d&project_id={p['id']}", headers=user["headers"]).json()
    assert filtered["summary"]["current"]["total_requests"] == 3
    by_provider = client.get("/api/v1/analytics/overview?range=30d&provider=gemini", headers=user["headers"]).json()
    assert by_provider["summary"]["current"]["total_requests"] == 1


def test_hourly_granularity_for_24h_and_custom_range_validation(client: TestClient, user):
    data = client.get("/api/v1/analytics/overview?range=24h", headers=user["headers"]).json()
    assert data["range"]["granularity"] == "hour" and len(data["timeseries"]) in (24, 25)
    now = utcnow()
    ok = client.get(
        "/api/v1/analytics/overview",
        params={"range": "custom", "start": (now - timedelta(days=3)).isoformat(), "end": now.isoformat()},
        headers=user["headers"],
    )
    assert ok.status_code == 200 and ok.json()["range"]["granularity"] == "day"
    inverted = client.get(
        "/api/v1/analytics/overview",
        params={"range": "custom", "start": now.isoformat(), "end": (now - timedelta(days=1)).isoformat()},
        headers=user["headers"],
    )
    assert inverted.status_code == 422
    missing = client.get("/api/v1/analytics/overview?range=custom", headers=user["headers"])
    assert missing.status_code == 422


def test_costs_endpoint_and_daily_monthly_summaries(client: TestClient, user, db):
    uid = user["user_id"]
    _record(db, uid, None, "openai", "gpt-4o", 1_000_000, 0)
    _record(db, uid, None, "openai", "mystery-model", 100, 100)  # unpriced
    data = client.get("/api/v1/analytics/costs?range=30d", headers=user["headers"]).json()
    assert abs(data["total_usd"] - 2.5) < 1e-9 and data["unpriced_requests"] == 1
    assert data["summaries"]["today_usd"] == 2.5 and data["summaries"]["month_to_date_usd"] == 2.5
    assert len(data["summaries"]["daily"]) == 30 and data["summaries"]["monthly"][-1]["cost_usd"] == 2.5


def test_request_logs_search_filter_sort_paginate_detail(client: TestClient, user, db):
    uid = user["user_id"]
    ids = [_record(db, uid, None, "openai", "gpt-4o", 10 * i, 5, latency=10 * i) for i in range(1, 6)]
    err = _record(db, uid, None, "anthropic", "claude-haiku-4-5", 0, 0, status=429, error="rate_limited")
    h = user["headers"]

    page = client.get("/api/v1/requests?page_size=2&page=1&sort=latency_ms&order=desc", headers=h).json()
    assert page["total"] == 6 and len(page["items"]) == 2 and page["items"][0]["latency_ms"] == 100
    page3 = client.get("/api/v1/requests?page_size=2&page=3&sort=latency_ms&order=desc", headers=h).json()
    assert len(page3["items"]) == 2

    errors = client.get("/api/v1/requests?status=error", headers=h).json()
    assert errors["total"] == 1 and errors["items"][0]["error_type"] == "rate_limited"
    search = client.get(f"/api/v1/requests?q={ids[2][4:14]}", headers=h).json()
    assert search["total"] == 1 and search["items"][0]["request_id"] == ids[2]
    wildcard = client.get("/api/v1/requests?q=%25", headers=h).json()  # literal % must not match everything
    assert wildcard["total"] == 0
    assert client.get("/api/v1/requests?provider=anthropic", headers=h).json()["total"] == 1
    assert client.get("/api/v1/requests?sort=bogus", headers=h).status_code == 422

    detail = client.get(f"/api/v1/requests/{err}", headers=h).json()
    assert (
        detail["http_status"] == 429
        and detail["error_message"] == "boom"
        and detail["cost_status"] in ("estimated", "unknown")
    )
    assert client.get("/api/v1/requests/req_doesnotexist", headers=h).status_code == 404
    assert set(client.get("/api/v1/requests/models", headers=h).json()) == {"gpt-4o", "claude-haiku-4-5"}
