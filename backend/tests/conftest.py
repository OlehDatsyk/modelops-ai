"""Test fixtures.

Tests run against a real PostgreSQL database (``TEST_DATABASE_URL``; default: the docker compose
``modelops_test`` database). The schema is built with the Alembic migrations, so migrations are
exercised on every run. Provider HTTP calls are mocked with respx — no paid API calls are made.
"""

from __future__ import annotations

import os

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://modelops:modelops@127.0.0.1:5434/modelops_test"
        ),
        "JWT_SECRET_KEY": "test-jwt-secret-key-0123456789-abcdefghijklmnop",
        "MASTER_ENCRYPTION_KEY": "test-master-encryption-key-0123456789-abcdefgh",
        "AI_ANALYST_PROVIDER": "",
        "AI_ANALYST_MODEL": "",
        "AI_ANALYST_API_KEY": "",
        "CORS_ORIGINS": "http://localhost:5173",
        "STATIC_DIR": "/nonexistent",
        "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
        "RATE_LIMIT_API_PER_MINUTE": "10000",
        "RATE_LIMIT_GATEWAY_PER_MINUTE": "10000",
        "MAX_REQUEST_BYTES": "200000",
    }
)

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_engine, get_sessionmaker
from app.services.pricing import seed_reference_pricing

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Sup3r-Secret-Pass"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = get_settings().database_url
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        tables = (
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
            )
            .scalars()
            .all()
        )
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    limiter.reset()


@pytest.fixture(autouse=True)
def _seed_pricing(_clean_db) -> None:
    with get_sessionmaker()() as db:
        seed_reference_pricing(db)


@pytest.fixture
def db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


def register(client: TestClient, email: str | None = None, password: str = PASSWORD) -> dict:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": "Test"})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "email": email,
        "user_id": data["user"]["id"],
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


@pytest.fixture
def user(client: TestClient) -> dict:
    return register(client)


@pytest.fixture
def other_user(client: TestClient) -> dict:
    # A separate client so the two users' refresh cookies do not mix.
    from app.main import app

    with TestClient(app) as c2:
        return register(c2)


def create_project(client: TestClient, headers: dict, name: str = "Support Bot", providers=None) -> dict:
    resp = client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "description": "test",
            "allowed_providers": providers or ["openai", "anthropic", "gemini"],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_key(client: TestClient, headers: dict, project_id: str) -> str:
    resp = client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "ci"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


def add_credential(client: TestClient, headers: dict, provider: str, key: str = "sk-test-provider-key-123456") -> dict:
    resp = client.put(f"/api/v1/providers/{provider}", json={"api_key": key, "validate_now": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def gateway_setup(client: TestClient, user: dict) -> dict:
    """A user with a project, a project key and credentials for all three providers."""
    project = create_project(client, user["headers"])
    key = create_key(client, user["headers"], project["id"])
    for provider in ("openai", "anthropic", "gemini"):
        add_credential(client, user["headers"], provider, key=f"sk-{provider}-secret-value-abcdef")
    return {**user, "project": project, "key": key, "gw": {"Authorization": f"Bearer {key}"}}
