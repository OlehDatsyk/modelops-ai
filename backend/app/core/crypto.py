"""Symmetric encryption for provider credentials.

MASTER_ENCRYPTION_KEY may contain one or more comma-separated secrets (>= 32 characters each).
Each secret is stretched with HKDF-SHA256 into a Fernet key (AES-128-CBC + HMAC-SHA256).
The first key encrypts; all keys can decrypt, which allows key rotation:

    MASTER_ENCRYPTION_KEY="<new-secret>,<old-secret>"

then run ``python -m app.cli rotate-keys`` to re-encrypt stored credentials with the new key.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

_HKDF_INFO = b"modelops-ai/provider-credentials/v1"


class DecryptionError(Exception):
    """Raised when a stored secret cannot be decrypted with the configured keys."""


def _derive_fernet_key(secret: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO)
    return base64.urlsafe_b64encode(hkdf.derive(secret.encode("utf-8")))


@lru_cache
def _cipher_for(master: str) -> MultiFernet:
    secrets_ = [s.strip() for s in master.split(",") if s.strip()]
    return MultiFernet([Fernet(_derive_fernet_key(s)) for s in secrets_])


def _cipher() -> MultiFernet:
    return _cipher_for(get_settings().master_encryption_key)


def encrypt_secret(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:  # wrong/rotated key or tampered data
        raise DecryptionError("stored credential could not be decrypted") from exc


def rotate_secret(token: str) -> str:
    """Re-encrypt a token with the primary (first) key."""
    return _cipher().rotate(token.encode("ascii")).decode("ascii")


def mask_secret(secret: str) -> str:
    """Return a non-reversible hint such as ``sk-p…9xQa``."""
    secret = secret.strip()
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:4]}…{secret[-4:]}"
