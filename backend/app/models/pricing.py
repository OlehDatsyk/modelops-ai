from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class ModelPricing(UUIDPk, Timestamps, Base):
    """Price per one million tokens (USD).

    Rows with ``user_id`` NULL form the shared reference catalogue (seeded, read-only for users).
    Rows with a ``user_id`` are that user's overrides and take precedence.
    ``model`` is matched exactly first, then as the longest prefix (e.g. ``gpt-4o`` matches
    ``gpt-4o-2024-08-06``).
    """

    __tablename__ = "model_pricing"
    __table_args__ = (
        Index("ix_model_pricing_lookup", "provider", "model"),
        Index(
            "uq_model_pricing_scope",
            "user_id",
            "provider",
            "model",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_price_per_mtok: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    output_price_per_mtok: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    # seed | manual
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    # True only when someone has confirmed the price against the provider's published pricing.
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(String(300), default="", nullable=False)
