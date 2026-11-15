"""Maintenance commands.

python -m app.cli seed-pricing     Insert missing reference prices (never overwrites)
python -m app.cli rotate-keys      Re-encrypt provider credentials with the first MASTER_ENCRYPTION_KEY
python -m app.cli check            Verify configuration and database connectivity
python -m app.cli generate-secrets Print fresh random values for JWT_SECRET_KEY and MASTER_ENCRYPTION_KEY
"""

from __future__ import annotations

import secrets
import sys

from sqlalchemy import select, text


def seed_pricing() -> None:
    from app.db.session import get_sessionmaker
    from app.services.pricing import seed_reference_pricing

    with get_sessionmaker()() as db:
        print(f"Reference pricing: {seed_reference_pricing(db)} row(s) inserted.")


def rotate_keys() -> None:
    from app.core.crypto import rotate_secret
    from app.db.session import get_sessionmaker
    from app.models import ProviderCredential

    with get_sessionmaker()() as db:
        creds = db.scalars(select(ProviderCredential)).all()
        for cred in creds:
            cred.encrypted_key = rotate_secret(cred.encrypted_key)
        db.commit()
        print(f"Re-encrypted {len(creds)} credential(s) with the primary key.")


def check() -> None:
    from app.core.config import get_settings
    from app.db.session import get_engine

    settings = get_settings()
    print(f"Environment: {settings.environment}")
    with get_engine().connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar()
    print(f"Database: connected (PostgreSQL {version})")
    print(f"AI Analyst configured: {settings.analyst_configured}")


def generate_secrets() -> None:
    print(f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"MASTER_ENCRYPTION_KEY={secrets.token_urlsafe(48)}")


COMMANDS = {
    "seed-pricing": seed_pricing,
    "rotate-keys": rotate_keys,
    "check": check,
    "generate-secrets": generate_secrets,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    COMMANDS[sys.argv[1]]()
