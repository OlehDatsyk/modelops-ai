from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk, utcnow

MONEY = Numeric(18, 8)
PRICE = Numeric(14, 6)


class ApiRequest(UUIDPk, Base):
    """Safe metadata for one gateway request. Prompts and completions are never stored."""

    __tablename__ = "api_requests"
    __table_args__ = (
        Index("ix_api_requests_user_created", "user_id", "created_at"),
        Index("ix_api_requests_user_project_created", "user_id", "project_id", "created_at"),
        Index("ix_api_requests_user_provider_created", "user_id", "provider", "created_at"),
        Index("ix_api_requests_user_status_created", "user_id", "status", "created_at"),
    )

    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("project_api_keys.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)
    streamed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # success | error
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(String(500))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Pricing snapshot used for the cost estimate (kept even if pricing changes later)
    pricing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_pricing.id", ondelete="SET NULL"))
    pricing_model_key: Mapped[str | None] = mapped_column(String(120))
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(PRICE)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(PRICE)
    pricing_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cost_input_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    cost_output_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    cost_total_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    cost_status: Mapped[str] = mapped_column(String(12), default="unknown", nullable=False)  # estimated|unknown
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UsageDaily(UUIDPk, Base):
    """Daily roll-up (UTC days) maintained transactionally alongside ``api_requests``."""

    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("user_id", "project_key", "provider", "model", "day", name="uq_usage_daily_bucket"),
        Index("ix_usage_daily_user_day", "user_id", "day"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    # project_key mirrors project_id as text ("" when none) so the unique constraint works with NULLs.
    project_key: Mapped[str] = mapped_column(String(36), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    unpriced_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms_sum: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
