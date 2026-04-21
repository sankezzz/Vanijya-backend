from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException

from app.modules.chat.domain.entities import (
    ConversationEntity,
    ConvStatus,
    MessageEntity,
)
from app.modules.chat.domain.repository import IChatRepository


class OpenChatUseCase:
    """
    Anyone can open a blank DM with any other user regardless of follow status.
    - If no conversation exists: create one (status=requested) + save first message.
    - If conversation already exists: return it as-is (let the router decide next action).
    """

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(
        self,
        sender_id: UUID,
        participant_id: UUID,
        first_message: str,
    ) -> tuple[ConversationEntity, MessageEntity, bool]:
        if sender_id == participant_id:
            raise HTTPException(status_code=400, detail="Cannot open a chat with yourself.")

        conv, created = self.repo.get_or_create_dm(sender_id, participant_id)

        if conv.status == ConvStatus.BLOCKED:
            raise HTTPException(status_code=403, detail="This conversation is blocked.")

        # Save first message regardless — if already active, it sends normally
        message = self.repo.save_message(
            context_type="dm",
            context_id=conv.id,
            sender_id=sender_id,
            body=first_message,
            message_type="text",
        )

        return conv, message, created


class SendMessageUseCase:
    """
    Send a message inside an existing conversation.
    Rules:
      - requested: only the original sender can message (request is still pending)
      - active:    both members can message freely
      - blocked:   nobody can message
    """

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(
        self,
        sender_id: UUID,
        conv_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_url: Optional[str] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
    ) -> MessageEntity:
        conv = self.repo.get_conversation(conv_id, sender_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        if conv.status == ConvStatus.BLOCKED:
            raise HTTPException(status_code=403, detail="This conversation is blocked.")

        if conv.status == ConvStatus.REQUESTED:
            initiator_id = self.repo.get_conversation_initiator(conv_id)
            if sender_id != initiator_id:
                raise HTTPException(
                    status_code=403,
                    detail="Waiting for the other person to accept the chat request.",
                )

        if not self.repo.is_member(conv_id, sender_id):
            raise HTTPException(status_code=403, detail="Not a member of this conversation.")

        return self.repo.save_message(
            context_type="dm",
            context_id=conv_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            media_url=media_url,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
        )


class AcceptConversationUseCase:
    """
    Receiver accepts the chat request → status becomes active.
    Only the non-initiating member (the receiver) can accept.
    """

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(self, user_id: UUID, conv_id: UUID) -> ConversationEntity:
        conv = self.repo.get_conversation(conv_id, user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        if conv.status != ConvStatus.REQUESTED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot accept: conversation is already '{conv.status}'.",
            )

        initiator_id = self.repo.get_conversation_initiator(conv_id)
        if user_id == initiator_id:
            raise HTTPException(status_code=403, detail="You cannot accept your own chat request.")

        return self.repo.set_conversation_status(conv_id, ConvStatus.ACTIVE)


class DeclineConversationUseCase:
    """
    Receiver declines → status becomes blocked.
    Sender will not be able to send further messages.
    """

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(self, user_id: UUID, conv_id: UUID) -> ConversationEntity:
        conv = self.repo.get_conversation(conv_id, user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        if conv.status != ConvStatus.REQUESTED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot decline: conversation is already '{conv.status}'.",
            )

        initiator_id = self.repo.get_conversation_initiator(conv_id)
        if user_id == initiator_id:
            raise HTTPException(status_code=403, detail="You cannot decline your own chat request.")

        return self.repo.set_conversation_status(conv_id, ConvStatus.BLOCKED)


class GetConversationsUseCase:
    """List all conversations for a user (active + requested), newest first."""

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(self, user_id: UUID, page: int = 1, per_page: int = 20) -> list[ConversationEntity]:
        return self.repo.get_conversations(user_id, page, per_page)


class GetMessagesUseCase:
    """
    Cursor-based message history for a conversation.
    User must be a member to read messages.
    """

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(
        self,
        user_id: UUID,
        conv_id: UUID,
        before: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[MessageEntity]:
        if not self.repo.is_member(conv_id, user_id):
            raise HTTPException(status_code=403, detail="Not a member of this conversation.")

        limit = min(limit, 100)  # hard cap
        return self.repo.get_messages("dm", conv_id, before, limit)


class MarkReadUseCase:
    """Mark all messages in a conversation as read for a user."""

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(self, user_id: UUID, conv_id: UUID) -> None:
        if not self.repo.is_member(conv_id, user_id):
            raise HTTPException(status_code=403, detail="Not a member of this conversation.")

        self.repo.mark_read(conv_id, user_id)


class GetGroupMessagesUseCase:
    """Cursor-based message history for a group. Sender must be a member."""

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(
        self,
        user_id: UUID,
        group_id: UUID,
        before: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[MessageEntity]:
        role = self.repo.get_group_member_role(group_id, user_id)
        if role is None:
            raise HTTPException(status_code=403, detail="Not a member of this group.")

        limit = min(limit, 100)
        return self.repo.get_messages("group", group_id, before, limit)


class SendGroupMessageUseCase:
    """Send a message into a group chat with membership and permission checks."""

    def __init__(self, repo: IChatRepository):
        self.repo = repo

    def execute(
        self,
        sender_id: UUID,
        group_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_url: Optional[str] = None,
        media_metadata: Optional[dict] = None,
        reply_to_id: Optional[UUID] = None,
    ) -> MessageEntity:
        chat_perm = self.repo.get_group_chat_perm(group_id)
        if chat_perm is None:
            raise HTTPException(status_code=404, detail="Group not found.")

        role = self.repo.get_group_member_role(group_id, sender_id)
        if role is None:
            raise HTTPException(status_code=403, detail="Not a member of this group.")

        if self.repo.is_group_member_frozen(group_id, sender_id):
            raise HTTPException(status_code=403, detail="You are frozen in this group.")

        if chat_perm == "admins_only" and role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can send messages in this group.")

        return self.repo.save_message(
            context_type="group",
            context_id=group_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            media_url=media_url,
            media_metadata=media_metadata,
            reply_to_id=reply_to_id,
        )
