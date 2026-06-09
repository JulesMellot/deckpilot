from __future__ import annotations

import asyncio
import time
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
        self.safe_mode_enabled = True
        self.live_controls_armed_until = 0.0
        self.connected_controllers: dict[str, ConnectionInfo] = {}
        self.logs = deque(maxlen=config.log_buffer_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._subscriber_queue_size = 64

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._subscriber_queue_size)
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload}
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    async def add_log(self, level: str, source: str, message: str) -> None:
        async with self._lock:
            entry = LogEntry.now(level=level, source=source, message=message)
            self.logs.append(entry)
        await self.publish("log", entry.to_dict())

    async def set_transport(self, **updates: Any) -> None:
        async with self._lock:
            changed = False
            for key, value in updates.items():
                if getattr(self.transport, key) != value:
                    setattr(self.transport, key, value)
                    changed = True
            if not changed:
                return
            snapshot = self.transport.to_dict()
        await self.publish("transport", snapshot)

    async def set_preview_enabled(self, enabled: bool) -> None:
        self.preview_enabled = enabled
        await self.publish("preview", {"enabled": enabled})

    async def set_remote_enabled(self, enabled: bool) -> None:
        self.remote_enabled = enabled
        await self.publish("remote", {"enabled": enabled})

    async def set_safe_mode(self, enabled: bool) -> None:
        self.safe_mode_enabled = enabled
        if not enabled:
            self.live_controls_armed_until = 0.0
        await self.publish("safety", self.safety_snapshot())

    async def arm_live_controls(self, seconds: int = 10) -> None:
        self.live_controls_armed_until = time.monotonic() + max(1, seconds)
        await self.publish("safety", self.safety_snapshot())

    def live_controls_armed(self) -> bool:
        return time.monotonic() < self.live_controls_armed_until

    def safety_snapshot(self) -> Dict[str, Any]:
        remaining = max(0, int(self.live_controls_armed_until - time.monotonic()))
        return {
            "safe_mode_enabled": self.safe_mode_enabled,
            "live_controls_armed": self.live_controls_armed(),
            "armed_seconds_remaining": remaining,
        }

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
