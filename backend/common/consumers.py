from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class PingConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Unauthenticated smoke-test socket (dev/health). Real consumers arrive in Phase 4."""

    async def connect(self) -> None:
        await self.accept()

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        await self.send_json({"type": "pong", "echo": content})
