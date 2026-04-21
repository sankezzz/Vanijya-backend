from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.modules.chat.presentation.connection_manager import manager

ws_router = APIRouter(tags=["Chat WebSocket"])


@ws_router.websocket("/ws/chat/{user_id}")
async def chat_ws(user_id: UUID, websocket: WebSocket):
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keeps connection alive; ignores client pings
    except WebSocketDisconnect:
        manager.disconnect(user_id)
