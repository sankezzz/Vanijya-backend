from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.modules.chat.domain.entities import ConvSendGuard, ConversationEntity, MessageEntity


class IChatRepository(ABC):

    @abstractmethod
    def get_or_create_dm(self, sender_id: UUID, participant_id: UUID) -> tuple[ConversationEntity, bool]:
        ...

    @abstractmethod
    def get_conversation(self, conv_id: UUID, requesting_user_id: UUID) -> Optional[ConversationEntity]:
        ...

    @abstractmethod
    def get_conversations(self, user_id: UUID, page: int, per_page: int) -> list[ConversationEntity]:
        ...

    @abstractmethod
    def set_conversation_status(self, conv_id: UUID, status: str) -> ConversationEntity:
        ...

    @abstractmethod
    def save_message(
        self,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        body: Optional[str],
        message_type: str = "text",
        media_url: Optional[str] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
    ) -> MessageEntity:
        ...

    @abstractmethod
    def get_messages(
        self,
        context_type: str,
        context_id: UUID,
        before: Optional[datetime],
        limit: int,
    ) -> list[MessageEntity]:
        ...

    @abstractmethod
    def mark_read(self, conv_id: UUID, user_id: UUID) -> None:
        ...

    @abstractmethod
    def is_member(self, conv_id: UUID, user_id: UUID) -> bool:
        ...

    @abstractmethod
    def get_other_member_id(self, conv_id: UUID, user_id: UUID) -> Optional[UUID]:
        ...

    @abstractmethod
    def get_conv_send_info(self, conv_id: UUID, sender_id: UUID) -> Optional[ConvSendGuard]:
        """Single-query check: membership + status + receiver_id + sender profile."""
        ...

    @abstractmethod
    def persist_message(
        self,
        msg_id: UUID,
        sent_at: datetime,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        body: Optional[str],
        message_type: str,
        media_url: Optional[str],
        media_metadata: Optional[dict],
        location_lat: Optional[float],
        location_lon: Optional[float],
        reply_to_id: Optional[UUID],
    ) -> None:
        """Fire-and-forget INSERT used as a background task after WS push."""
        ...

    # ── Group helpers ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_group_member_role(self, group_id: UUID, user_id: UUID) -> Optional[str]:
        """Return 'admin' | 'member' | None if not a member."""

    @abstractmethod
    def is_group_member_frozen(self, group_id: UUID, user_id: UUID) -> bool:
        """Return True if the member exists and is_frozen=True."""

    @abstractmethod
    def get_group_chat_perm(self, group_id: UUID) -> Optional[str]:
        """Return group.chat_perm ('all_members' | 'admins_only'), or None if group not found."""

    @abstractmethod
    def get_group_member_ids(self, group_id: UUID) -> list[UUID]:
        """Return all user_ids that are members of the group (for WS push)."""
