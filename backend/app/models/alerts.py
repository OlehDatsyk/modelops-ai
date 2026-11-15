from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, utcnow


class Budget(UUIDPk, Timestamps, Base):
    __tablename__ = "budgets"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # daily | monthly
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    warning_thresholds: Mapped[list] = mapped_column(JSON, default=lambda: [50, 80, 100], nullable=False)
    # When true, the gateway rejects requests once the limit is reached for the current period.
    enforce_limit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AlertRule(UUIDPk, Timestamps, Base):
    __tablename__ = "alert_rules"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # error_rate (percent) | request_volume (requests) | token_usage (tokens) | spend (USD)
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    min_requests: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPk, Base):
    """In-app notification. ``dedupe_key`` prevents repeating the same alert for the same period."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # budget | alert | system
    severity: Mapped[str] = mapped_column(String(10), default="info", nullable=False)  # info|warning|critical
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
