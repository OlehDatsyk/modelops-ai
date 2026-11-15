"""Shared FastAPI dependencies: database session, authenticated user and gateway identity."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decode_access_token, sha256_hex
from app.db.base import utcnow
from app.db.session import get_db
from app.models import Project, ProjectApiKey, User

_UNAUTHORIZED = AppError(401, "unauthorized", "Authentication required", headers={"WWW-Authenticate": "Bearer"})


def client_ip(request: Request) -> str:
    """Client address for rate limiting. Takes the entry appended by the last trusted proxy, never a
    client-controlled left-most X-Forwarded-For value."""
    hops = get_settings().trusted_proxy_hops
    if hops:
        forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _bearer(request)
    if not token:
        raise _UNAUTHORIZED
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise AppError(401, "invalid_token", "Invalid or expired access token") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active or payload.get("ver") != user.token_version:
        raise AppError(401, "invalid_token", "Invalid or expired access token")
    rate_limit.enforce(f"api:{user.id}", get_settings().rate_limit_api_per_minute)
    return user


@dataclass(frozen=True)
class GatewayIdentity:
    user_id: uuid.UUID
    project_id: uuid.UUID
    api_key_id: uuid.UUID
    allowed_providers: tuple[str, ...]


def _gateway_key(request: Request) -> str | None:
    # OpenAI SDKs send "Authorization: Bearer", Anthropic SDKs "x-api-key", Google SDKs "x-goog-api-key".
    return _bearer(request) or request.headers.get("x-api-key") or request.headers.get("x-goog-api-key")


def get_gateway_identity(request: Request, db: Session = Depends(get_db)) -> GatewayIdentity:
    raw = _gateway_key(request)
    if not raw or not raw.startswith("mk_"):
        raise AppError(
            401,
            "invalid_project_key",
            "A valid ModelOps project API key is required (Authorization: Bearer mk_...)",
        )
    rate_limit.enforce(f"gw-ip:{client_ip(request)}", get_settings().rate_limit_gateway_per_minute * 5)
    row = db.execute(
        select(ProjectApiKey, Project)
        .join(Project, Project.id == ProjectApiKey.project_id)
        .where(ProjectApiKey.key_hash == sha256_hex(raw), ProjectApiKey.revoked_at.is_(None))
    ).first()
    if row is None:
        raise AppError(401, "invalid_project_key", "Invalid or revoked project API key")
    key, project = row
    user = db.get(User, key.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "invalid_project_key", "Invalid or revoked project API key")
    rate_limit.enforce(f"gw:{key.id}", get_settings().rate_limit_gateway_per_minute)

    now = utcnow()
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now
        db.commit()
    return GatewayIdentity(
        user_id=key.user_id,
        project_id=project.id,
        api_key_id=key.id,
        allowed_providers=tuple(project.allowed_providers or ()),
    )
