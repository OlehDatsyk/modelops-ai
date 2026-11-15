"""Cross-user data isolation: every resource must be invisible and immutable to other users."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.providers.base import Usage
from app.services.usage import RequestRecord, record_request
from tests.conftest import add_credential, create_key, create_project


def test_users_cannot_access_each_others_resources(client: TestClient, user, other_user, db):
    a, b = user["headers"], other_user["headers"]
    project = create_project(client, a, "Alice project")
    create_key(client, a, project["id"])
    add_credential(client, a, "openai")
    budget = client.post(
        "/api/v1/budgets", json={"name": "B", "period": "monthly", "limit_usd": "10"}, headers=a
    ).json()
    rule = client.post(
        "/api/v1/alert-rules", json={"name": "R", "metric": "error_rate", "threshold": "5"}, headers=a
    ).json()
    pricing = client.post(
        "/api/v1/pricing",
        json={
            "provider": "openai",
            "model": "alice-model",
            "input_price_per_mtok": "1",
            "output_price_per_mtok": "1",
        },
        headers=a,
    ).json()
    rid = "req_isolation0001"
    record_request(
        db,
        RequestRecord(
            rid,
            uuid.UUID(user["user_id"]),
            uuid.UUID(project["id"]),
            None,
            "openai",
            "gpt-4o",
            "chat",
            False,
            200,
            50,
            Usage(10, 10),
        ),
    )

    # Listing endpoints show nothing of Alice's to Bob.
    assert client.get("/api/v1/projects", headers=b).json() == []
    assert client.get("/api/v1/requests", headers=b).json()["total"] == 0
    assert client.get("/api/v1/budgets", headers=b).json() == []
    assert client.get("/api/v1/alert-rules", headers=b).json() == []
    assert all(not p["configured"] for p in client.get("/api/v1/providers", headers=b).json())
    assert all(p["model"] != "alice-model" for p in client.get("/api/v1/pricing", headers=b).json())
    assert (
        client.get("/api/v1/analytics/overview?range=30d", headers=b).json()["summary"]["current"]["total_requests"]
        == 0
    )

    # Direct access by ID returns 404 (no existence oracle) and changes nothing.
    pid = project["id"]
    assert client.get(f"/api/v1/projects/{pid}", headers=b).status_code == 404
    assert client.patch(f"/api/v1/projects/{pid}", json={"name": "pwned"}, headers=b).status_code == 404
    assert client.delete(f"/api/v1/projects/{pid}", headers=b).status_code == 404
    assert client.get(f"/api/v1/projects/{pid}/keys", headers=b).status_code == 404
    assert client.post(f"/api/v1/projects/{pid}/keys", json={"name": "x"}, headers=b).status_code == 404
    assert client.get(f"/api/v1/requests/{rid}", headers=b).status_code == 404
    assert client.get(f"/api/v1/analytics/overview?project_id={pid}", headers=b).status_code == 404
    assert client.delete(f"/api/v1/budgets/{budget['id']}", headers=b).status_code == 404
    assert (
        client.put(
            f"/api/v1/alert-rules/{rule['id']}",
            json={"name": "x", "metric": "spend", "threshold": "1"},
            headers=b,
        ).status_code
        == 404
    )
    assert client.patch(f"/api/v1/pricing/{pricing['id']}", json={"verified": True}, headers=b).status_code == 404
    assert (
        client.post(
            "/api/v1/budgets",
            json={"name": "x", "period": "daily", "limit_usd": "1", "project_id": pid},
            headers=b,
        ).status_code
        == 404
    )
    assert client.delete("/api/v1/providers/openai", headers=b).status_code == 404

    # Alice still sees her untouched data.
    assert client.get(f"/api/v1/projects/{pid}", headers=a).json()["name"] == "Alice project"
    assert client.get("/api/v1/requests", headers=a).json()["total"] == 1


def test_project_key_only_uses_its_owners_credentials(client: TestClient, user, other_user):
    # Bob has an OpenAI key; Alice does not. Alice's project key must not reach Bob's credential.
    add_credential(client, other_user["headers"], "openai")
    project = create_project(client, user["headers"])
    key = create_key(client, user["headers"], project["id"])
    resp = client.post(
        "/api/v1/gateway/openai/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "provider_not_configured"
    assert client.get("/api/v1/requests", headers=other_user["headers"]).json()["total"] == 0
