"""Password hashing, JWT access tokens, refresh tokens and project API keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)

PROJECT_KEY_PREFIX = "mk_"


# --- Passwords -------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# A pre-computed hash used to equalise timing when the e-mail address does not exist.
DUMMY_PASSWORD_HASH = _hasher.hash("modelops-timing-equaliser")


# --- JWT access tokens ---------------------------------------------------------------
def create_access_token(user_id: uuid.UUID, token_version: int) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_minutes * 60
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token. Raises jwt.PyJWTError on any problem."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "iat"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# --- Opaque tokens (refresh tokens, project API keys) -----------------------------
def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def generate_project_key() -> str:
    """High-entropy project key (~256 bits). Only its SHA-256 hash is stored."""
    return PROJECT_KEY_PREFIX + secrets.token_urlsafe(32)


def project_key_display_prefix(raw_key: str) -> str:
    return raw_key[:10]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
