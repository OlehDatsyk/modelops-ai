"""Unit tests for hashing, tokens, encryption, redaction and rate limiting."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.crypto import DecryptionError, _cipher_for, decrypt_secret, encrypt_secret, mask_secret
from app.core.logging import redact
from app.core.rate_limit import RateLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_project_key,
    hash_password,
    sha256_hex,
    verify_password,
)


def test_password_hash_roundtrip_and_salting():
    h1, h2 = hash_password("Correct-Horse-9"), hash_password("Correct-Horse-9")
    assert h1 != h2 and h1.startswith("$argon2id$")
    assert verify_password(h1, "Correct-Horse-9")
    assert not verify_password(h1, "wrong")
    assert not verify_password("not-a-hash", "Correct-Horse-9")


def test_access_token_roundtrip():
    uid = uuid.uuid4()
    token, expires_in = create_access_token(uid, 3)
    payload = decode_access_token(token)
    assert payload["sub"] == str(uid) and payload["ver"] == 3 and expires_in == 15 * 60


def test_access_token_rejects_expired_tampered_and_wrong_type():
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(hours=1)
    expired = jwt.encode(
        {"sub": "x", "type": "access", "iat": int(past.timestamp()), "exp": int(past.timestamp()) + 1},
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)

    token, _ = create_access_token(uuid.uuid4(), 0)
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token[:-2] + ("AA" if not token.endswith("AA") else "BB"))

    other = jwt.encode({"sub": "x", "type": "refresh", "iat": 1, "exp": 4_000_000_000}, settings.jwt_secret_key)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(other)

    forged = jwt.encode({"sub": "x", "type": "access", "iat": 1, "exp": 4_000_000_000}, "another-secret-" * 4)
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(forged)


def test_encrypt_decrypt_and_ciphertext_is_not_plaintext():
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    token = encrypt_secret(secret)
    assert secret not in token
    assert decrypt_secret(token) == secret
    assert encrypt_secret(secret) != token  # random IV


def test_decrypt_with_wrong_key_fails_and_rotation_works():
    old = _cipher_for("old-secret-old-secret-old-secret-old-secret")
    token = old.encrypt(b"sk-rotate-me").decode()
    with pytest.raises(DecryptionError):
        decrypt_secret(token)
    rotated = _cipher_for("new-secret-new-secret-new-secret-new-secret,old-secret-old-secret-old-secret-old-secret")
    new_token = rotated.rotate(token.encode())
    assert _cipher_for("new-secret-new-secret-new-secret-new-secret").decrypt(new_token) == b"sk-rotate-me"


def test_mask_secret():
    assert mask_secret("sk-proj-1234567890abcd") == "sk-p…abcd"
    assert mask_secret("short") == "•••••"


def test_project_key_format_and_hash():
    key = generate_project_key()
    assert key.startswith("mk_") and len(key) > 40
    assert sha256_hex(key) == sha256_hex(key) and len(sha256_hex(key)) == 64
    assert generate_project_key() != key


def test_redaction_masks_credentials():
    text = (
        "key sk-proj-ABCDEFGHIJKLMNOP and AIzaSyA1234567890abcdefghijk and "
        "mk_abcdefghijklmnopqrstuvwxyz and Bearer abcdefghijklmnopqrstuvwxyz"
    )
    out = redact(text)
    for leaked in (
        "sk-proj-ABCDEFGHIJKLMNOP",
        "AIzaSyA1234567890abcdefghijk",
        "mk_abcdefghijklmnopqrstuvwxyz",
        "abcdefghijklmnopqrstuvwxyz",
    ):
        assert leaked not in out
    assert out.count("[REDACTED]") == 4


def test_rate_limiter_window():
    rl = RateLimiter()
    assert all(rl.hit("k", 3, 0.2)[0] for _ in range(3))
    allowed, retry = rl.hit("k", 3, 0.2)
    assert not allowed and retry >= 1
    time.sleep(0.25)
    assert rl.hit("k", 3, 0.2)[0]
    assert rl.hit("other", 3, 0.2)[0]


def test_settings_require_secrets(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings()
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "")
    with pytest.raises(ValueError, match="MASTER_ENCRYPTION_KEY"):
        Settings()


def test_database_url_normalisation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    assert Settings().database_url == "postgresql+psycopg://u:p@host:5432/db"
    assert Settings().effective_database_url == "postgresql+psycopg://u:p@host:5432/db"
    monkeypatch.setenv("DATABASE_NAME", "modelops")
    assert Settings().effective_database_url == "postgresql+psycopg://u:p@host:5432/modelops"
    monkeypatch.setenv("DATABASE_NAME", "bad;name")
    with pytest.raises(ValueError):
        Settings()
