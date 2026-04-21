from sqlalchemy.orm import Session
from fastapi import Depends

from app.dependencies import get_db
from app.modules.chat.data.repository_impl import ChatRepository
from app.modules.chat.domain.repository import IChatRepository
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


def get_chat_repo(db: Session = Depends(get_db)) -> IChatRepository:
    return ChatRepository(db)


def get_open_chat_uc(repo: IChatRepository = Depends(get_chat_repo)) -> OpenChatUseCase:
    return OpenChatUseCase(repo)


def get_send_message_uc(repo: IChatRepository = Depends(get_chat_repo)) -> SendMessageUseCase:
    return SendMessageUseCase(repo)


def get_accept_uc(repo: IChatRepository = Depends(get_chat_repo)) -> AcceptConversationUseCase:
    return AcceptConversationUseCase(repo)


def get_decline_uc(repo: IChatRepository = Depends(get_chat_repo)) -> DeclineConversationUseCase:
    return DeclineConversationUseCase(repo)


def get_conversations_uc(repo: IChatRepository = Depends(get_chat_repo)) -> GetConversationsUseCase:
    return GetConversationsUseCase(repo)


def get_messages_uc(repo: IChatRepository = Depends(get_chat_repo)) -> GetMessagesUseCase:
    return GetMessagesUseCase(repo)


def get_mark_read_uc(repo: IChatRepository = Depends(get_chat_repo)) -> MarkReadUseCase:
    return MarkReadUseCase(repo)


def get_group_message_uc(repo: IChatRepository = Depends(get_chat_repo)) -> SendGroupMessageUseCase:
    return SendGroupMessageUseCase(repo)


def get_group_messages_uc(repo: IChatRepository = Depends(get_chat_repo)) -> GetGroupMessagesUseCase:
    return GetGroupMessagesUseCase(repo)
