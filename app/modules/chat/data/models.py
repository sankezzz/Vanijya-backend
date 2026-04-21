import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database.base import Base


class Conversation(Base):
    """
    A DM thread between exactly two users.
    status: requested  — sender opened chat, first message held pending
            active     — receiver accepted, both can message freely
            blocked    — receiver declined or user blocked
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(String(10), nullable=False, default="dm")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    members: Mapped[list["ConversationMember"]] = relationship(
        "ConversationMember", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        primaryjoin="and_(Message.context_type=='dm', foreign(Message.context_id)==Conversation.id)",
        viewonly=True,
        order_by="Message.created_at.desc()",
    )


class ConversationMember(Base):
    """Tracks per-user state inside a conversation — read position, mute."""

    __tablename__ = "conversation_members"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="members"
    )


class Message(Base):
    """
    Single message. Works for both DM (context_type='dm') and group chat
    (context_type='group'). context_id points to conversations.id or groups.id.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    context_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'dm' | 'group'
    context_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text"
        # text | image | video | document | audio | location | system
    )
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    media_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    location_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reply_to_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ChatAttachment(Base):
    """
    Mirrors media messages for the 'Shared Media' gallery view.
    Indexed separately so media queries don't scan the full messages table.
    """

    __tablename__ = "chat_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    context_type: Mapped[str] = mapped_column(String(10), nullable=False)
    context_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # image | video | document | audio
    media_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
