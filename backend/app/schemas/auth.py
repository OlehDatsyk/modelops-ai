from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _check_password_strength(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters")
    classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        raise ValueError("Password must contain at least three of: lowercase, uppercase, digit, symbol")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = Field(default="", max_length=120)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _check_password_strength(v)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    created_at: datetime
    last_login_at: datetime | None
    password_changed_at: datetime | None


class UpdateProfileRequest(BaseModel):
    full_name: str = Field(max_length=120)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirm: str = Field(description='Must be the literal text "DELETE"')


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_agent: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool = False


TokenResponse.model_rebuild()
