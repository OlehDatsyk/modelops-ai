"""Health, middleware (headers, request IDs, size limits, CORS), errors and migrations."""

from __future__ import annotations

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db.session import get_engine
from tests.conftest import alembic_config


def test_health_reports_database(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200 and resp.json()["database"] == "ok"
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    assert client.get("/api/v1/meta").json()["analyst_configured"] is False


def test_security_headers_and_request_id(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-request-id"].startswith("req_")
    supplied = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123456"})
    assert supplied.headers["x-request-id"].startswith("req_")  # never trusted: IDs must be unique
    assert supplied.headers["x-request-id"] != resp.headers["x-request-id"]


def test_client_ip_uses_trusted_proxy_hop(monkeypatch):
    from starlette.requests import Request

    from app.api.deps import client_ip
    from app.core.config import get_settings

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],
        "client": ("10.0.0.1", 1234),
    }
    assert client_ip(Request(scope)) == "10.0.0.1"  # no trusted proxies: socket peer
    monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 1)
    assert client_ip(Request(scope)) == "203.0.113.9"  # appended by our proxy, not the spoofed value


def test_body_size_limit(client: TestClient, user):
    big = "x" * 250_000
    resp = client.post("/api/v1/projects", json={"name": "big", "description": big}, headers=user["headers"])
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "payload_too_large"


def test_unknown_api_route_is_json_404(client: TestClient):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"


def test_errors_do_not_leak_internals(client: TestClient, user):
    resp = client.get("/api/v1/projects/not-a-uuid", headers=user["headers"])
    assert resp.status_code == 422
    body = resp.json()
    assert "request_id" in body["error"] and "Traceback" not in resp.text


def test_cors_only_allows_configured_origin(client: TestClient):
    ok = client.options(
        "/api/v1/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.options(
        "/api/v1/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in evil.headers


def test_rate_limit_on_login(client: TestClient, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 3)
    codes = [client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"}).status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429


def test_migrations_downgrade_and_upgrade_cleanly():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    assert set(inspect(get_engine()).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    tables = set(inspect(get_engine()).get_table_names())
    expected = {
        "users",
        "refresh_tokens",
        "provider_credentials",
        "projects",
        "project_api_keys",
        "api_requests",
        "usage_daily",
        "model_pricing",
        "budgets",
        "alert_rules",
        "notifications",
        "analyst_conversations",
        "analyst_messages",
    }
    assert expected <= tables
    indexes = {i["name"] for i in inspect(get_engine()).get_indexes("api_requests")}
    assert {"ix_api_requests_user_created", "ix_api_requests_user_project_created"} <= indexes
