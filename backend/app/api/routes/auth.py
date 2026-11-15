"""Registration, login, token refresh, logout and account management."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    password_needs_rehash,
    sha256_hex,
    verify_password,
)
from app.db.base import utcnow
from app.db.session import get_db
from app.models import RefreshToken, User
from app.schemas.auth import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    LoginRequest,
    RegisterRequest,
    SessionOut,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "modelops_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
ROTATION_GRACE_SECONDS = 20


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _end_rotation_grace(db: Session, user_id: uuid.UUID) -> None:
    """After logout / revocation no previously rotated token may be exchanged, even within the grace window."""
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(rotated_at=None))


def _issue_tokens(db: Session, user: User, request: Request, response: Response) -> TokenResponse:
    settings = get_settings()
    raw = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=sha256_hex(raw),
            user_agent=(request.headers.get("user-agent") or "")[:255],
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    db.commit()
    _set_refresh_cookie(response, raw)
    access, expires_in = create_access_token(user.id, user.token_version)
    return TokenResponse(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit.enforce(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError(409, "email_taken", "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    user.last_login_at = utcnow()
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "email_taken", "An account with this email already exists") from None
    return _issue_tokens(db, user, request, response)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    rate_limit.enforce(f"login:{body.email.lower()}", settings.rate_limit_auth_per_minute)
    rate_limit.enforce(f"login-ip:{client_ip(request)}", settings.rate_limit_auth_per_minute * 5)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    invalid = AppError(401, "invalid_credentials", "Incorrect email or password")
    if user is None:
        verify_password(DUMMY_PASSWORD_HASH, body.password)  # equalise timing
        raise invalid
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise AppError(423, "account_locked", "Too many failed attempts. Try again in a few minutes.")
    if not verify_password(user.password_hash, body.password) or not user.is_active:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
        db.commit()
        raise invalid
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    return _issue_tokens(db, user, request, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Rotate the refresh token (httpOnly cookie) and return a new access token."""
    rate_limit.enforce(f"refresh:{client_ip(request)}", 60)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AppError(401, "no_session", "No active session")
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
    now = utcnow()
    if token is None or token.expires_at <= now:
        _clear_refresh_cookie(response)
        raise AppError(401, "session_expired", "Session expired. Please sign in again.")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "session_expired", "Session expired. Please sign in again.")
    if token.revoked_at is not None:
        in_grace = token.rotated_at is not None and now - token.rotated_at <= timedelta(seconds=ROTATION_GRACE_SECONDS)
        if not in_grace:
            # A revoked token being replayed suggests theft: revoke every session of this user.
            db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            db.commit()
            _clear_refresh_cookie(response)
            raise AppError(401, "session_revoked", "Session revoked. Please sign in again.")
        # Concurrent refresh from another tab within the grace window: issue a fresh pair.
    else:
        token.revoked_at = now
        token.rotated_at = now
        db.commit()
    return _issue_tokens(db, user, request, response)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
        if token:
            token.revoked_at = token.revoked_at or utcnow()
            _end_rotation_grace(db, token.user_id)
            db.commit()
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: UpdateProfileRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.full_name = body.full_name.strip()
    db.commit()
    return user


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rate_limit.enforce(f"pw:{user.id}", 5)
    if not verify_password(user.password_hash, body.current_password):
        raise AppError(400, "invalid_password", "Current password is incorrect")
    if body.current_password == body.new_password:
        raise AppError(400, "same_password", "New password must differ from the current one")
    now = utcnow()
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = now
    user.token_version += 1  # invalidates outstanding access tokens
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    _end_rotation_grace(db, user.id)
    db.commit()
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_hash = sha256_hex(request.cookies.get(REFRESH_COOKIE, "")) if request.cookies.get(REFRESH_COOKIE) else None
    rows = db.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        )
        .order_by(RefreshToken.created_at.desc())
    ).all()
    return [SessionOut.model_validate(r).model_copy(update={"current": r.token_hash == current_hash}) for r in rows]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = db.scalar(select(RefreshToken).where(RefreshToken.id == session_id, RefreshToken.user_id == user.id))
    if token is None:
        raise not_found("Session")
    token.revoked_at = token.revoked_at or utcnow()
    _end_rotation_grace(db, user.id)
    db.commit()
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = utcnow()
    user.token_version += 1
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    _end_rotation_grace(db, user.id)
    db.commit()
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.delete("/me", status_code=204)
def delete_account(
    body: DeleteAccountRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete the account and all of its data (cascading foreign keys)."""
    if body.confirm != "DELETE":
        raise AppError(400, "confirmation_required", 'Type "DELETE" to confirm account deletion')
    if not verify_password(user.password_hash, body.password):
        raise AppError(400, "invalid_password", "Password is incorrect")
    db.delete(user)
    db.commit()
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response
