from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow


class AnalystConversation(UUIDPk, Timestamps, Base):
    __tablename__ = "analyst_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    messages: Mapped[list[AnalystMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalystMessage.created_at",
    )


class AnalystMessage(UUIDPk, Base):
    __tablename__ = "analyst_messages"
    __table_args__ = (Index("ix_analyst_messages_conv_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyst_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Tool calls made and the metrics they returned (supporting evidence shown in the UI).
    tool_results: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped[AnalystConversation] = relationship(back_populates="messages")
