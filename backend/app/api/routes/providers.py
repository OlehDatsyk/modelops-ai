"""Provider credentials: store (encrypted), validate, inspect (masked) and delete."""

from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core import rate_limit
from app.core.crypto import DecryptionError, decrypt_secret, encrypt_secret, mask_secret
from app.core.errors import AppError, not_found
from app.db.base import utcnow
from app.db.session import get_db
from app.models import ProviderCredential, User
from app.providers.registry import get_adapter, get_http_client
from app.schemas.resources import CredentialOut, CredentialUpsert, ProviderStatusOut

router = APIRouter(prefix="/providers", tags=["providers"])

Provider = Literal["openai", "anthropic", "gemini"]


def _get_cred(db: Session, user: User, provider: str) -> ProviderCredential | None:
    return db.scalar(
        select(ProviderCredential).where(ProviderCredential.user_id == user.id, ProviderCredential.provider == provider)
    )


async def _validate(db: Session, cred: ProviderCredential, api_key: str) -> None:
    adapter = get_adapter(cred.provider)
    try:
        result = await adapter.validate_key(get_http_client(), api_key)
        cred.status, cred.status_message, models = result.status, result.message, result.models
        if result.status == "valid":
            cred.available_models = models
    except httpx.TimeoutException:
        cred.status, cred.status_message = "error", "Validation timed out contacting the provider."
    except httpx.HTTPError:
        cred.status, cred.status_message = "error", "Could not connect to the provider."
    cred.last_validated_at = utcnow()
    await run_in_threadpool(db.commit)


@router.get("", response_model=list[ProviderStatusOut])
def list_providers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    creds = {
        c.provider: c for c in db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user.id)).all()
    }
    out = []
    for name in ("openai", "anthropic", "gemini"):
        cred = creds.get(name)
        out.append(
            ProviderStatusOut(
                provider=name,
                display_name=get_adapter(name).display_name,
                configured=cred is not None,
                credential=CredentialOut.model_validate(cred) if cred else None,
            )
        )
    return out


@router.put("/{provider}", response_model=CredentialOut)
async def upsert_credential(
    provider: Provider,
    body: CredentialUpsert,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rate_limit.enforce(f"cred:{user.id}", 20)
    cred = await run_in_threadpool(_get_cred, db, user, provider)
    if cred is None:
        cred = ProviderCredential(user_id=user.id, provider=provider)
        db.add(cred)
    cred.encrypted_key = encrypt_secret(body.api_key)
    cred.key_hint = mask_secret(body.api_key)
    cred.status, cred.status_message, cred.available_models = "unverified", "Not validated yet.", []
    cred.last_validated_at = None
    await run_in_threadpool(db.commit)
    if body.validate_now:
        await _validate(db, cred, body.api_key)
    return CredentialOut.model_validate(cred)


@router.post("/{provider}/validate", response_model=CredentialOut)
async def validate_credential(
    provider: Provider, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rate_limit.enforce(f"cred:{user.id}", 20)
    cred = await run_in_threadpool(_get_cred, db, user, provider)
    if cred is None:
        raise not_found("Provider credential")
    try:
        api_key = decrypt_secret(cred.encrypted_key)
    except DecryptionError:
        raise AppError(409, "credential_unavailable", "Stored key cannot be decrypted; please re-enter it.") from None
    await _validate(db, cred, api_key)
    return CredentialOut.model_validate(cred)


@router.delete("/{provider}", status_code=204)
def delete_credential(provider: Provider, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cred = _get_cred(db, user, provider)
    if cred is None:
        raise not_found("Provider credential")
    db.delete(cred)
    db.commit()
    return Response(status_code=204)
