"""Authentication and account-management integration tests."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.models import RefreshToken, User
from tests.conftest import PASSWORD, register


def test_register_returns_tokens_and_sets_httponly_cookie(client: TestClient):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "Alice@Example.com", "password": PASSWORD, "full_name": " Alice "},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["full_name"] == "Alice"
    assert "password_hash" not in body["user"] and PASSWORD not in resp.text and "argon2" not in resp.text
    cookie = resp.headers["set-cookie"]
    assert "modelops_rt=" in cookie and "HttpOnly" in cookie and "samesite=strict" in cookie.lower()
    assert "Path=/api/v1/auth" in cookie


def test_register_rejects_duplicate_and_weak_password(client: TestClient):
    register(client, "dup@example.com")
    resp = client.post("/api/v1/auth/register", json={"email": "DUP@example.com", "password": PASSWORD})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "email_taken"
    weak = client.post("/api/v1/auth/register", json={"email": "weak@example.com", "password": "password"})
    assert weak.status_code == 422
    # The submitted password must not be echoed in validation errors.
    assert "password" not in str(weak.json()["error"].get("details", [])).replace("'password'", "")


def test_password_stored_hashed(client: TestClient, db):
    register(client, "hash@example.com")
    user = db.scalar(select(User).where(User.email == "hash@example.com"))
    assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash


def test_login_success_and_failure(client: TestClient):
    register(client, "login@example.com")
    ok = client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": "Wrong-Pass-123"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert unknown.status_code == 401 and unknown.json()["error"]["message"] == bad.json()["error"]["message"]


def test_account_lockout_after_repeated_failures(client: TestClient):
    register(client, "lock@example.com")
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": "Wrong-Pass-123"})
    resp = client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": PASSWORD})
    assert resp.status_code == 423


def test_protected_routes_require_valid_token(client: TestClient):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/projects", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/v1/analytics/overview", headers={"Authorization": "Basic abc"}).status_code == 401


def test_me_and_profile_update(client: TestClient, user):
    me = client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.status_code == 200 and me.json()["email"] == user["email"]
    upd = client.patch("/api/v1/auth/me", json={"full_name": "New Name"}, headers=user["headers"])
    assert upd.json()["full_name"] == "New Name"


def test_refresh_rotates_token_and_detects_reuse(client: TestClient, db):
    register(client, "refresh@example.com")
    old_cookie = client.cookies.get("modelops_rt")
    first = client.post("/api/v1/auth/refresh")
    assert first.status_code == 200 and first.json()["access_token"]
    new_cookie = client.cookies.get("modelops_rt")
    assert new_cookie and new_cookie != old_cookie

    # Another tab replaying the just-rotated token within the grace window gets a fresh session.
    client.cookies.set("modelops_rt", old_cookie, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 200

    # Replaying a rotated token after the grace window is treated as theft: every session is revoked.
    db.execute(update(RefreshToken).values(rotated_at=RefreshToken.rotated_at - timedelta(minutes=5)))
    db.commit()
    client.cookies.set("modelops_rt", old_cookie, path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "session_revoked"
    db.expire_all()
    active = db.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))).all()
    assert active == []


def test_logged_out_token_cannot_use_rotation_grace(client: TestClient):
    register(client, "grace@example.com")
    old_cookie = client.cookies.get("modelops_rt")
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("modelops_rt", old_cookie, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_cookie(client: TestClient):
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_refresh_token(client: TestClient):
    register(client, "logout@example.com")
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_change_password_invalidates_existing_tokens(client: TestClient, user):
    bad = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Nope-nope-123", "new_password": "Another-Pass-456"},
        headers=user["headers"],
    )
    assert bad.status_code == 400
    ok = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "Another-Pass-456"},
        headers=user["headers"],
    )
    assert ok.status_code == 204
    assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 401
    relog = client.post("/api/v1/auth/login", json={"email": user["email"], "password": "Another-Pass-456"})
    assert relog.status_code == 200


def test_sessions_list_and_logout_all(client: TestClient, user):
    client.post("/api/v1/auth/login", json={"email": user["email"], "password": PASSWORD})
    sessions = client.get("/api/v1/auth/sessions", headers=user["headers"]).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    revoke = client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=user["headers"])
    assert revoke.status_code == 204
    assert client.post("/api/v1/auth/logout-all", headers=user["headers"]).status_code == 204
    assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 401


def test_delete_account_requires_confirmation_and_cascades(client: TestClient, user, db):
    from tests.conftest import create_project

    create_project(client, user["headers"])
    no_confirm = client.request(
        "DELETE", "/api/v1/auth/me", json={"password": PASSWORD, "confirm": "nope"}, headers=user["headers"]
    )
    assert no_confirm.status_code == 400
    wrong_pw = client.request(
        "DELETE",
        "/api/v1/auth/me",
        json={"password": "Wrong-123-abc", "confirm": "DELETE"},
        headers=user["headers"],
    )
    assert wrong_pw.status_code == 400
    ok = client.request(
        "DELETE", "/api/v1/auth/me", json={"password": PASSWORD, "confirm": "DELETE"}, headers=user["headers"]
    )
    assert ok.status_code == 204
    assert db.scalar(select(User).where(User.email == user["email"])) is None
    assert client.post("/api/v1/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 401
