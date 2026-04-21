from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class UserSnap:
    """Minimal user info embedded in conversation / message responses."""
    user_id: UUID
    profile_id: int
    name: str
    is_verified: bool


@dataclass
class LastMessage:
    """Summary of the most recent message shown in the conversation list."""
    id: UUID
    body: Optional[str]
    message_type: str   # text | image | video | document | audio | location | system
    sender_id: UUID
    sent_at: datetime


@dataclass
class ConversationEntity:
    id: UUID
    status: str             # requested | active | blocked
    participant: UserSnap   # the other person in the DM
    last_message: Optional[LastMessage]
    unread_count: int
    is_muted: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class MessageEntity:
    id: UUID
    context_id: UUID        # conversation_id or group_id
    context_type: str       # 'dm' | 'group'
    sender: UserSnap
    message_type: str
    body: Optional[str]
    media_url: Optional[str]
    media_metadata: Optional[dict]
    location_lat: Optional[float]
    location_lon: Optional[float]
    reply_to_id: Optional[UUID]
    is_deleted: bool
    sent_at: datetime


# ── Status constants ──────────────────────────────────────────────────────────

class ConvStatus:
    REQUESTED = "requested"
    ACTIVE    = "active"
    BLOCKED   = "blocked"
