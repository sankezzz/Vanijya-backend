from uuid import UUID

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._active: dict[UUID, WebSocket] = {}

    async def connect(self, user_id: UUID, ws: WebSocket) -> None:
        await ws.accept()
        self._active[user_id] = ws

    def disconnect(self, user_id: UUID) -> None:
        self._active.pop(user_id, None)

    async def push(self, user_id: UUID, payload: dict) -> None:
        ws = self._active.get(user_id)
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            self.disconnect(user_id)


manager = ConnectionManager()
