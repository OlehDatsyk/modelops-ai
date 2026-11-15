from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk

PROVIDERS = ("openai", "anthropic", "gemini")


class ProviderCredential(UUIDPk, Timestamps, Base):
    """A user's API key for an upstream AI provider. The key is stored encrypted only."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(32), nullable=False)
    # unverified | valid | invalid | error
    status: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    status_message: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    available_models: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
