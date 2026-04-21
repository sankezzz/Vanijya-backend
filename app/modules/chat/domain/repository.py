from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.modules.chat.domain.entities import ConversationEntity, MessageEntity


class IChatRepository(ABC):

    # ── Conversations ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_or_create_dm(
        self, sender_id: UUID, participant_id: UUID
    ) -> tuple[ConversationEntity, bool]:
        """
        Find existing DM between the two users or create one with
        status=requested. Returns (entity, created).
        """

    @abstractmethod
    def get_conversation(
        self, conv_id: UUID, requesting_user_id: UUID
    ) -> Optional[ConversationEntity]:
        """Load a single conversation visible to requesting_user_id."""

    @abstractmethod
    def get_conversations(
        self, user_id: UUID, page: int, per_page: int
    ) -> list[ConversationEntity]:
        """All conversations for a user, sorted by updated_at DESC."""

    @abstractmethod
    def set_conversation_status(
        self, conv_id: UUID, status: str
    ) -> ConversationEntity:
        """Update conversation status. Used by accept / decline."""

    # ── Messages ──────────────────────────────────────────────────────────────

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
        """Persist a message and bump conversations.updated_at."""

    @abstractmethod
    def get_messages(
        self,
        context_type: str,
        context_id: UUID,
        before: Optional[datetime],
        limit: int,
    ) -> list[MessageEntity]:
        """
        Cursor-based history. Returns up to `limit` messages
        with created_at < before (or newest if before is None).
        """

    @abstractmethod
    def mark_read(self, conv_id: UUID, user_id: UUID) -> None:
        """Set conversation_members.last_read_at = NOW() for this user."""

    # ── Membership helpers ────────────────────────────────────────────────────

    @abstractmethod
    def is_member(self, conv_id: UUID, user_id: UUID) -> bool:
        """Return True if user_id is a member of the conversation."""

    @abstractmethod
    def get_other_member_id(self, conv_id: UUID, user_id: UUID) -> Optional[UUID]:
        """Return the other participant's user_id in a DM."""

    @abstractmethod
    def get_conversation_initiator(self, conv_id: UUID) -> Optional[UUID]:
        """Return the user_id who sent the first message (i.e. opened the chat)."""

    # ── Group helpers ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_group_member_role(self, group_id: UUID, user_id: UUID) -> Optional[str]:
        """Return the member's role ('admin'|'member') or None if not a member."""

    @abstractmethod
    def get_group_chat_perm(self, group_id: UUID) -> Optional[str]:
        """Return group.chat_perm or None if group doesn't exist."""

    @abstractmethod
    def is_group_member_frozen(self, group_id: UUID, user_id: UUID) -> bool:
        """Return True if the member exists and is frozen."""

    @abstractmethod
    def get_group_member_ids(self, group_id: UUID) -> list[UUID]:
        """Return all user_ids that are members of the group."""

    @abstractmethod
    def bump_group_activity(self, group_id: UUID) -> None:
        """Increment group_activity_cache.messages_24h by 1."""
