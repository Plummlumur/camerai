import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        for websocket in list(self._clients):
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.warning("dropping unreachable websocket client")
                self._clients.discard(websocket)
