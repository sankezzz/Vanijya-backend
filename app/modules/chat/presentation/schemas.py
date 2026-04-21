from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Request schemas ───────────────────────────────────────────────────────────

class OpenChatRequest(BaseModel):
    """POST /{user_id}/conversations — open a new DM and send first message."""
    participant_id: UUID
    message: str = Field(..., min_length=1, max_length=4000)


class SendMessageRequest(BaseModel):
    """POST /{user_id}/conversations/{conv_id}/messages"""
    body: Optional[str] = Field(None, max_length=4000)
    message_type: str = Field("text", pattern="^(text|image|video|document|audio|location|system)$")
    media_url: Optional[str] = Field(None, max_length=500)
    media_metadata: Optional[dict] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    reply_to_id: Optional[UUID] = None


class GroupMessageRequest(BaseModel):
    """POST /{user_id}/groups/{group_id}/messages"""
    body: Optional[str] = Field(None, max_length=4000)
    message_type: str = Field("text", pattern="^(text|image|video|document|audio|location|system)$")
    media_url: Optional[str] = Field(None, max_length=500)
    media_metadata: Optional[dict] = None
    reply_to_id: Optional[UUID] = None


# ── Response schemas ──────────────────────────────────────────────────────────

class UserSnapOut(BaseModel):
    user_id: UUID
    profile_id: int
    name: str
    is_verified: bool


class LastMessageOut(BaseModel):
    id: UUID
    body: Optional[str]
    message_type: str
    sender_id: UUID
    sent_at: datetime


class ConversationOut(BaseModel):
    id: UUID
    status: str
    participant: UserSnapOut
    last_message: Optional[LastMessageOut]
    unread_count: int
    is_muted: bool
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: UUID
    context_id: UUID
    context_type: str
    sender: UserSnapOut
    message_type: str
    body: Optional[str]
    media_url: Optional[str]
    media_metadata: Optional[dict]
    location_lat: Optional[float]
    location_lon: Optional[float]
    reply_to_id: Optional[UUID]
    is_deleted: bool
    sent_at: datetime
