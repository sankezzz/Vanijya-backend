from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, aliased

from app.modules.chat.data.models import (
    ChatAttachment,
    Conversation,
    ConversationMember,
    Message,
)
from app.modules.groups.models import Group, GroupActivityCache, GroupMember
from app.modules.chat.domain.entities import (
    ConvStatus,
    ConversationEntity,
    LastMessage,
    MessageEntity,
    UserSnap,
)
from app.modules.chat.domain.repository import IChatRepository
from app.modules.profile.models import Profile


# ── Private helpers ───────────────────────────────────────────────────────────

def _profile_snap(profile: Profile) -> UserSnap:
    return UserSnap(
        user_id=profile.users_id,
        profile_id=profile.id,
        name=profile.name,
        is_verified=profile.is_verified,
    )


def _last_message(db: Session, context_id: UUID) -> Optional[LastMessage]:
    row = (
        db.query(Message)
        .filter(
            Message.context_type == "dm",
            Message.context_id == context_id,
            Message.is_deleted.is_(False),
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if row is None:
        return None
    return LastMessage(
        id=row.id,
        body=row.body,
        message_type=row.message_type,
        sender_id=row.sender_id,
        sent_at=row.created_at,
    )


def _unread_count(db: Session, conv_id: UUID, user_id: UUID) -> int:
    member = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user_id,
        )
        .first()
    )
    if member is None:
        return 0

    q = db.query(func.count(Message.id)).filter(
        Message.context_type == "dm",
        Message.context_id == conv_id,
        Message.is_deleted.is_(False),
        Message.sender_id != user_id,
    )
    if member.last_read_at is not None:
        q = q.filter(Message.created_at > member.last_read_at)

    return q.scalar() or 0


def _build_conversation(
    db: Session,
    conv: Conversation,
    requesting_user_id: UUID,
) -> Optional[ConversationEntity]:
    """Build a ConversationEntity from an ORM row for the requesting user."""
    members = (
        db.query(ConversationMember)
        .filter(ConversationMember.conversation_id == conv.id)
        .all()
    )

    other_member = next(
        (m for m in members if m.user_id != requesting_user_id), None
    )
    my_member = next(
        (m for m in members if m.user_id == requesting_user_id), None
    )

    if other_member is None or my_member is None:
        return None

    other_profile = (
        db.query(Profile)
        .filter(Profile.users_id == other_member.user_id)
        .first()
    )
    if other_profile is None:
        return None

    return ConversationEntity(
        id=conv.id,
        status=conv.status,
        participant=_profile_snap(other_profile),
        last_message=_last_message(db, conv.id),
        unread_count=_unread_count(db, conv.id, requesting_user_id),
        is_muted=my_member.is_muted,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _build_message(db: Session, msg: Message) -> MessageEntity:
    sender_profile = (
        db.query(Profile).filter(Profile.users_id == msg.sender_id).first()
    )
    sender_snap = (
        _profile_snap(sender_profile)
        if sender_profile
        else UserSnap(
            user_id=msg.sender_id,
            profile_id=0,
            name="Unknown",
            is_verified=False,
        )
    )
    return MessageEntity(
        id=msg.id,
        context_id=msg.context_id,
        context_type=msg.context_type,
        sender=sender_snap,
        message_type=msg.message_type,
        body=msg.body,
        media_url=msg.media_url,
        media_metadata=msg.media_metadata,
        location_lat=msg.location_lat,
        location_lon=msg.location_lon,
        reply_to_id=msg.reply_to_id,
        is_deleted=msg.is_deleted,
        sent_at=msg.created_at,
    )


# ── Repository implementation ─────────────────────────────────────────────────

class ChatRepository(IChatRepository):

    def __init__(self, db: Session):
        self.db = db

    # ── Conversations ─────────────────────────────────────────────────────────

    def get_or_create_dm(
        self, sender_id: UUID, participant_id: UUID
    ) -> tuple[ConversationEntity, bool]:
        """
        Find an existing DM between the two users or create one.
        Uses a self-join on conversation_members to find the shared conversation.
        """
        cm1 = aliased(ConversationMember)
        cm2 = aliased(ConversationMember)

        existing = (
            self.db.query(Conversation)
            .join(cm1, and_(
                cm1.conversation_id == Conversation.id,
                cm1.user_id == sender_id,
            ))
            .join(cm2, and_(
                cm2.conversation_id == Conversation.id,
                cm2.user_id == participant_id,
            ))
            .filter(Conversation.type == "dm")
            .first()
        )

        if existing:
            entity = _build_conversation(self.db, existing, sender_id)
            return entity, False

        # Create new conversation
        now = datetime.now(timezone.utc)
        conv = Conversation(
            id=uuid4(),
            type="dm",
            status=ConvStatus.REQUESTED,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conv)
        self.db.flush()  # get conv.id before adding members

        self.db.add(ConversationMember(
            conversation_id=conv.id,
            user_id=sender_id,
            joined_at=now,
        ))
        self.db.add(ConversationMember(
            conversation_id=conv.id,
            user_id=participant_id,
            joined_at=now,
        ))
        self.db.commit()
        self.db.refresh(conv)

        entity = _build_conversation(self.db, conv, sender_id)
        return entity, True

    def get_conversation(
        self, conv_id: UUID, requesting_user_id: UUID
    ) -> Optional[ConversationEntity]:
        conv = (
            self.db.query(Conversation)
            .filter(Conversation.id == conv_id)
            .first()
        )
        if conv is None:
            return None
        if not self.is_member(conv_id, requesting_user_id):
            return None
        return _build_conversation(self.db, conv, requesting_user_id)

    def get_conversations(
        self, user_id: UUID, page: int, per_page: int
    ) -> list[ConversationEntity]:
        offset = (page - 1) * per_page

        conv_ids = (
            self.db.query(ConversationMember.conversation_id)
            .filter(ConversationMember.user_id == user_id)
            .subquery()
        )

        convs = (
            self.db.query(Conversation)
            .filter(Conversation.id.in_(conv_ids))
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )

        result = []
        for conv in convs:
            entity = _build_conversation(self.db, conv, user_id)
            if entity:
                result.append(entity)
        return result

    def set_conversation_status(
        self, conv_id: UUID, status: str
    ) -> ConversationEntity:
        conv = (
            self.db.query(Conversation)
            .filter(Conversation.id == conv_id)
            .first()
        )
        conv.status = status
        conv.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conv)

        # Return from the perspective of the receiver (any member — caller decides)
        member = (
            self.db.query(ConversationMember)
            .filter(ConversationMember.conversation_id == conv_id)
            .first()
        )
        return _build_conversation(self.db, conv, member.user_id)

    # ── Messages ──────────────────────────────────────────────────────────────

    def save_message(
        self,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_url: Optional[str] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
    ) -> MessageEntity:
        now = datetime.now(timezone.utc)

        msg = Message(
            id=uuid4(),
            context_type=context_type,
            context_id=context_id,
            sender_id=sender_id,
            message_type=message_type,
            body=body,
            media_url=media_url,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            is_deleted=False,
            created_at=now,
        )
        self.db.add(msg)
        self.db.flush()

        # Mirror media messages into chat_attachments for gallery view
        if media_url and message_type in ("image", "video", "document", "audio"):
            self.db.add(ChatAttachment(
                id=uuid4(),
                message_id=msg.id,
                context_type=context_type,
                context_id=context_id,
                media_type=message_type,
                media_url=media_url,
                created_at=now,
            ))

        # Bump conversation updated_at so list sorts correctly
        if context_type == "dm":
            self.db.query(Conversation).filter(
                Conversation.id == context_id
            ).update({"updated_at": now})

        # Increment group activity cache for recommendation scoring
        if context_type == "group":
            self.db.query(GroupActivityCache).filter(
                GroupActivityCache.group_id == context_id
            ).update({"messages_24h": GroupActivityCache.messages_24h + 1})

        self.db.commit()
        self.db.refresh(msg)

        return _build_message(self.db, msg)

    def get_messages(
        self,
        context_type: str,
        context_id: UUID,
        before: Optional[datetime],
        limit: int,
    ) -> list[MessageEntity]:
        q = self.db.query(Message).filter(
            Message.context_type == context_type,
            Message.context_id == context_id,
        )
        if before is not None:
            q = q.filter(Message.created_at < before)

        rows = q.order_by(Message.created_at.desc()).limit(limit).all()
        return [_build_message(self.db, m) for m in rows]

    def mark_read(self, conv_id: UUID, user_id: UUID) -> None:
        self.db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user_id,
        ).update({"last_read_at": datetime.now(timezone.utc)})
        self.db.commit()

    # ── Membership helpers ────────────────────────────────────────────────────

    def is_member(self, conv_id: UUID, user_id: UUID) -> bool:
        return (
            self.db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == conv_id,
                ConversationMember.user_id == user_id,
            )
            .first()
        ) is not None

    def get_other_member_id(self, conv_id: UUID, user_id: UUID) -> Optional[UUID]:
        row = (
            self.db.query(ConversationMember.user_id)
            .filter(
                ConversationMember.conversation_id == conv_id,
                ConversationMember.user_id != user_id,
            )
            .first()
        )
        return row[0] if row else None

    def get_conversation_initiator(self, conv_id: UUID) -> Optional[UUID]:
        row = (
            self.db.query(Message.sender_id)
            .filter(
                Message.context_type == "dm",
                Message.context_id == conv_id,
            )
            .order_by(Message.created_at.asc())
            .first()
        )
        return row[0] if row else None

    # ── Group helpers ─────────────────────────────────────────────────────────

    def get_group_member_role(self, group_id: UUID, user_id: UUID) -> Optional[str]:
        row = (
            self.db.query(GroupMember)
            .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            .first()
        )
        return row.role if row else None

    def get_group_chat_perm(self, group_id: UUID) -> Optional[str]:
        row = self.db.query(Group).filter(Group.id == group_id).first()
        return row.chat_perm if row else None

    def is_group_member_frozen(self, group_id: UUID, user_id: UUID) -> bool:
        row = (
            self.db.query(GroupMember)
            .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            .first()
        )
        return bool(row and row.is_frozen)

    def get_group_member_ids(self, group_id: UUID) -> list[UUID]:
        rows = (
            self.db.query(GroupMember.user_id)
            .filter(GroupMember.group_id == group_id)
            .all()
        )
        return [r[0] for r in rows]

    def bump_group_activity(self, group_id: UUID) -> None:
        self.db.query(GroupActivityCache).filter(
            GroupActivityCache.group_id == group_id
        ).update({"messages_24h": GroupActivityCache.messages_24h + 1})
