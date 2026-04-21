"""
Chat & Messaging — 8 REST endpoints
Base prefix: /api/v1/chat

No auth token — acting user is always identified by {user_id} in the path.

Route order: specific paths before parameterised ones.
  /{user_id}/conversations          before  /{user_id}/conversations/{conv_id}/...
  /{user_id}/groups/{group_id}/...  separate branch
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.modules.chat.domain.entities import (
    ConversationEntity,
    LastMessage,
    MessageEntity,
    UserSnap,
)
from app.modules.chat.domain.use_cases import (
    AcceptConversationUseCase,
    DeclineConversationUseCase,
    GetConversationsUseCase,
    GetGroupMessagesUseCase,
    GetMessagesUseCase,
    MarkReadUseCase,
    OpenChatUseCase,
    SendGroupMessageUseCase,
    SendMessageUseCase,
)
from app.modules.chat.presentation.connection_manager import manager
from app.modules.chat.presentation.dependencies import (
    get_accept_uc,
    get_chat_repo,
    get_conversations_uc,
    get_decline_uc,
    get_group_message_uc,
    get_group_messages_uc,
    get_mark_read_uc,
    get_messages_uc,
    get_open_chat_uc,
    get_send_message_uc,
)
from app.modules.chat.domain.repository import IChatRepository
from app.modules.chat.presentation.schemas import (
    GroupMessageRequest,
    OpenChatRequest,
    SendMessageRequest,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


# ── Serialisers (entity → plain dict for ok()) ───────────────────────────────

def _snap(u: UserSnap) -> dict:
    return {
        "user_id": str(u.user_id),
        "profile_id": u.profile_id,
        "name": u.name,
        "is_verified": u.is_verified,
    }


def _last_msg(lm: Optional[LastMessage]) -> Optional[dict]:
    if lm is None:
        return None
    return {
        "id": str(lm.id),
        "body": lm.body,
        "message_type": lm.message_type,
        "sender_id": str(lm.sender_id),
        "sent_at": lm.sent_at.isoformat(),
    }


def _conv(c: ConversationEntity) -> dict:
    return {
        "id": str(c.id),
        "status": c.status,
        "participant": _snap(c.participant),
        "last_message": _last_msg(c.last_message),
        "unread_count": c.unread_count,
        "is_muted": c.is_muted,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _msg(m: MessageEntity) -> dict:
    return {
        "id": str(m.id),
        "context_id": str(m.context_id),
        "context_type": m.context_type,
        "sender": _snap(m.sender),
        "message_type": m.message_type,
        "body": m.body,
        "media_url": m.media_url,
        "media_metadata": m.media_metadata,
        "location_lat": m.location_lat,
        "location_lon": m.location_lon,
        "reply_to_id": str(m.reply_to_id) if m.reply_to_id else None,
        "is_deleted": m.is_deleted,
        "sent_at": m.sent_at.isoformat(),
    }


# ── 1. GET /{user_id}/conversations ──────────────────────────────────────────

@router.get("/{user_id}/conversations")
def list_conversations(
    user_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    uc: GetConversationsUseCase = Depends(get_conversations_uc),
):
    convs = uc.execute(user_id, page, per_page)
    return ok(
        {"conversations": [_conv(c) for c in convs], "page": page, "per_page": per_page},
        "Conversations fetched",
    )


# ── 2. POST /{user_id}/conversations — open chat + first message ──────────────

@router.post("/{user_id}/conversations", status_code=201)
def open_chat(
    user_id: UUID,
    payload: OpenChatRequest,
    background_tasks: BackgroundTasks,
    uc: OpenChatUseCase = Depends(get_open_chat_uc),
):
    conv, message, created = uc.execute(user_id, payload.participant_id, payload.message)
    msg_dict = _msg(message)
    background_tasks.add_task(
        manager.push,
        payload.participant_id,
        {"event": "new_message", "data": {"conversation_id": str(conv.id), "message": msg_dict}},
    )
    return ok(
        {"conversation": _conv(conv), "message": msg_dict, "created": created},
        "Chat opened" if created else "Existing chat returned",
    )


# ── 3. GET /{user_id}/conversations/{conv_id}/messages ───────────────────────

@router.get("/{user_id}/conversations/{conv_id}/messages")
def get_messages(
    user_id: UUID,
    conv_id: UUID,
    before: Optional[datetime] = Query(None, description="Cursor — fetch messages older than this timestamp"),
    limit: int = Query(50, ge=1, le=100),
    uc: GetMessagesUseCase = Depends(get_messages_uc),
):
    messages = uc.execute(user_id, conv_id, before, limit)
    return ok(
        {
            "messages": [_msg(m) for m in messages],
            "has_more": len(messages) == limit,
            "oldest_timestamp": messages[-1].sent_at.isoformat() if messages else None,
        },
        "Messages fetched",
    )


# ── 4. POST /{user_id}/conversations/{conv_id}/messages ──────────────────────

@router.post("/{user_id}/conversations/{conv_id}/messages", status_code=201)
def send_message(
    user_id: UUID,
    conv_id: UUID,
    payload: SendMessageRequest,
    background_tasks: BackgroundTasks,
    uc: SendMessageUseCase = Depends(get_send_message_uc),
    repo: IChatRepository = Depends(get_chat_repo),
):
    message = uc.execute(
        sender_id=user_id,
        conv_id=conv_id,
        body=payload.body,
        message_type=payload.message_type,
        media_url=payload.media_url,
        media_metadata=payload.media_metadata,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        reply_to_id=payload.reply_to_id,
    )
    msg_dict = _msg(message)
    receiver_id = repo.get_other_member_id(conv_id, user_id)
    if receiver_id:
        background_tasks.add_task(
            manager.push,
            receiver_id,
            {"event": "new_message", "data": {"conversation_id": str(conv_id), "message": msg_dict}},
        )
    return ok({"message": msg_dict}, "Message sent")


# ── 5. POST /{user_id}/conversations/{conv_id}/accept ────────────────────────

@router.post("/{user_id}/conversations/{conv_id}/accept")
def accept_conversation(
    user_id: UUID,
    conv_id: UUID,
    uc: AcceptConversationUseCase = Depends(get_accept_uc),
):
    conv = uc.execute(user_id, conv_id)
    return ok({"conversation": _conv(conv)}, "Chat request accepted")


# ── 6. POST /{user_id}/conversations/{conv_id}/decline ───────────────────────

@router.post("/{user_id}/conversations/{conv_id}/decline")
def decline_conversation(
    user_id: UUID,
    conv_id: UUID,
    uc: DeclineConversationUseCase = Depends(get_decline_uc),
):
    conv = uc.execute(user_id, conv_id)
    return ok({"conversation": _conv(conv)}, "Chat request declined")


# ── 7. POST /{user_id}/conversations/{conv_id}/read ──────────────────────────

@router.post("/{user_id}/conversations/{conv_id}/read")
def mark_read(
    user_id: UUID,
    conv_id: UUID,
    uc: MarkReadUseCase = Depends(get_mark_read_uc),
):
    uc.execute(user_id, conv_id)
    return ok(None, "Marked as read")


# ── 8. GET /{user_id}/groups/{group_id}/messages ─────────────────────────────

@router.get("/{user_id}/groups/{group_id}/messages")
def get_group_messages(
    user_id: UUID,
    group_id: UUID,
    before: Optional[datetime] = Query(None, description="Cursor — fetch messages older than this timestamp"),
    limit: int = Query(50, ge=1, le=100),
    uc: GetGroupMessagesUseCase = Depends(get_group_messages_uc),
):
    messages = uc.execute(user_id, group_id, before, limit)
    return ok(
        {
            "messages": [_msg(m) for m in messages],
            "has_more": len(messages) == limit,
            "oldest_timestamp": messages[-1].sent_at.isoformat() if messages else None,
        },
        "Group messages fetched",
    )


# ── 9. POST /{user_id}/groups/{group_id}/messages ────────────────────────────

@router.post("/{user_id}/groups/{group_id}/messages", status_code=201)
def send_group_message(
    user_id: UUID,
    group_id: UUID,
    payload: GroupMessageRequest,
    background_tasks: BackgroundTasks,
    uc: SendGroupMessageUseCase = Depends(get_group_message_uc),
    repo: IChatRepository = Depends(get_chat_repo),
):
    message = uc.execute(
        sender_id=user_id,
        group_id=group_id,
        body=payload.body,
        message_type=payload.message_type,
        media_url=payload.media_url,
        media_metadata=payload.media_metadata,
        reply_to_id=payload.reply_to_id,
    )
    msg_dict = _msg(message)
    member_ids = repo.get_group_member_ids(group_id)
    for member_id in member_ids:
        if member_id != user_id:
            background_tasks.add_task(
                manager.push,
                member_id,
                {"event": "new_group_message", "data": {"group_id": str(group_id), "message": msg_dict}},
            )
    return ok({"message": msg_dict}, "Group message sent")
