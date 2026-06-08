from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Dict, List

from app.core.config import AppConfig
from app.core.models import ConnectionInfo, LogEntry, TransportState


class AppState:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.transport = TransportState(video_format=config.default_video_format)
        self.remote_enabled = True
        self.preview_enabled = False
        self.playrange_clip_id: int | None = None
        self.connected_controllers: dict[str, ConnectionInfo] = {}
        self.logs = deque(maxlen=config.log_buffer_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            await queue.put({"type": event_type, "payload": payload})

    async def add_log(self, level: str, source: str, message: str) -> None:
        async with self._lock:
            entry = LogEntry.now(level=level, source=source, message=message)
            self.logs.append(entry)
        await self.publish("log", entry.to_dict())

    async def set_transport(self, **updates: Any) -> None:
        async with self._lock:
            for key, value in updates.items():
                setattr(self.transport, key, value)
            snapshot = self.transport.to_dict()
        await self.publish("transport", snapshot)

    async def set_preview_enabled(self, enabled: bool) -> None:
        self.preview_enabled = enabled
        await self.publish("preview", {"enabled": enabled})

    async def set_remote_enabled(self, enabled: bool) -> None:
        self.remote_enabled = enabled
        await self.publish("remote", {"enabled": enabled})

    async def add_controller(self, key: str, host: str, port: int) -> None:
        async with self._lock:
            self.connected_controllers[key] = ConnectionInfo.now(name=key, host=host, port=port)
            payload = self.connection_snapshot()
        await self.publish("connections", payload)

    async def remove_controller(self, key: str) -> None:
        async with self._lock:
            self.connected_controllers.pop(key, None)
            payload = self.connection_snapshot()
        await self.publish("connections", payload)

    def connection_snapshot(self) -> Dict[str, Any]:
        return {"clients": [item.to_dict() for item in self.connected_controllers.values()]}

    def logs_snapshot(self) -> List[Dict[str, Any]]:
        return [entry.to_dict() for entry in self.logs]
