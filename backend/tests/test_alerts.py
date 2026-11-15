"""Budgets, alert rules and notifications."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Notification
from app.providers.base import Usage
from app.services.alerts import evaluate_budgets, evaluate_rules
from app.services.usage import RequestRecord, record_request


def _rec(db, uid, inp=0, out=0, status=200, error=None, model="gpt-4o"):
    record_request(
        db,
        RequestRecord(
            "req_" + uuid.uuid4().hex[:16],
            uuid.UUID(uid),
            None,
            None,
            "openai",
            model,
            "chat",
            False,
            status,
            10,
            Usage(inp, out),
            error_type=error,
        ),
    )


def test_budget_crud_progress_and_threshold_notifications(client: TestClient, user, db):
    h = user["headers"]
    created = client.post(
        "/api/v1/budgets",
        json={"name": "Monthly", "period": "monthly", "limit_usd": "10", "warning_thresholds": [80, 50]},
        headers=h,
    )
    assert created.status_code == 201 and created.json()["warning_thresholds"] == [50, 80]
    bid = created.json()["id"]

    _rec(db, user["user_id"], inp=2_400_000)  # $6.00 -> 60%
    uid = uuid.UUID(user["user_id"])
    evaluate_budgets(db, uid, None)
    evaluate_budgets(db, uid, None)  # idempotent for the same threshold and period
    budgets = client.get("/api/v1/budgets", headers=h).json()
    assert budgets[0]["percent_used"] == 60.0 and float(budgets[0]["current_spend_usd"]) == 6.0
    notes = client.get("/api/v1/notifications", headers=h).json()
    assert notes["total"] == 1 and notes["unread"] == 1 and "50%" in notes["items"][0]["title"]

    _rec(db, user["user_id"], inp=1_000_000)  # $8.50 -> 85%
    evaluate_budgets(db, uid, None)
    assert client.get("/api/v1/notifications", headers=h).json()["total"] == 2

    upd = client.put(
        f"/api/v1/budgets/{bid}",
        json={"name": "Monthly", "period": "monthly", "limit_usd": "100", "enabled": False},
        headers=h,
    )
    assert upd.status_code == 200 and upd.json()["enabled"] is False
    bad = client.post("/api/v1/budgets", json={"name": "x", "period": "weekly", "limit_usd": "1"}, headers=h)
    assert bad.status_code == 422
    assert (
        client.post("/api/v1/budgets", json={"name": "x", "period": "daily", "limit_usd": "0"}, headers=h).status_code
        == 422
    )
    assert client.delete(f"/api/v1/budgets/{bid}", headers=h).status_code == 204


def test_error_rate_rule_triggers_once_within_cooldown(client: TestClient, user, db):
    h = user["headers"]
    rule = client.post(
        "/api/v1/alert-rules",
        json={
            "name": "Errors",
            "metric": "error_rate",
            "threshold": "20",
            "window_minutes": 60,
            "min_requests": 4,
        },
        headers=h,
    ).json()
    uid = uuid.UUID(user["user_id"])
    for _ in range(2):
        _rec(db, user["user_id"])
    _rec(db, user["user_id"], status=500, error="provider_error")
    assert evaluate_rules(db, uid, None) == 0  # below min_requests (3 < 4)
    _rec(db, user["user_id"], status=500, error="provider_error")
    assert evaluate_rules(db, uid, None) == 1  # 50% >= 20%
    assert evaluate_rules(db, uid, None) == 0  # cooldown
    note = db.scalar(select(Notification).where(Notification.kind == "alert"))
    assert "50.00%" in note.message and note.severity == "critical"
    assert client.get("/api/v1/alert-rules", headers=h).json()[0]["last_triggered_at"] is not None
    assert client.delete(f"/api/v1/alert-rules/{rule['id']}", headers=h).status_code == 204


def test_rule_validation(client: TestClient, user):
    h = user["headers"]
    assert (
        client.post("/api/v1/alert-rules", json={"name": "x", "metric": "cpu", "threshold": "1"}, headers=h).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/alert-rules",
            json={"name": "x", "metric": "spend", "threshold": "1", "window_minutes": 1},
            headers=h,
        ).status_code
        == 422
    )


def test_notification_read_and_delete(client: TestClient, user, db):
    from app.services.alerts import create_notification

    uid = uuid.UUID(user["user_id"])
    n1 = create_notification(db, uid, kind="system", severity="info", title="A", message="a", dedupe_key="k1")
    assert create_notification(db, uid, kind="system", severity="info", title="A", message="a", dedupe_key="k1") is None
    create_notification(db, uid, kind="system", severity="info", title="B", message="b")
    h = user["headers"]
    assert client.post(f"/api/v1/notifications/{n1.id}/read", headers=h).json()["read_at"] is not None
    assert client.get("/api/v1/notifications?unread_only=true", headers=h).json()["total"] == 1
    assert client.post("/api/v1/notifications/read-all", headers=h).status_code == 204
    assert client.get("/api/v1/notifications", headers=h).json()["unread"] == 0
    assert client.delete(f"/api/v1/notifications/{n1.id}", headers=h).status_code == 204
    assert client.get("/api/v1/notifications", headers=h).json()["total"] == 1
