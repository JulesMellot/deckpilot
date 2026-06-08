from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass
class ClipRecord:
    deck_id: int
    name: str
    folder: str
    filepath: str
    filename: str
    duration_seconds: float
    duration_timecode: str
    framerate: float
    codec: str
    width: int = 0
    height: int = 0
    is_vertical: bool = False
    thumbnail_path: str | None = None
    processing_state: str = "ready"
    loop_enabled: bool = False
    is_builtin: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransportState:
    status: str = "stopped"
    speed: int = 0
    slot_id: int = 1
    clip_id: int = 0
    display_timecode: str = "00:00:00:00"
    timecode: str = "00:00:00:00"
    video_format: str = "1080p25"
    loop: bool = False
    single_clip: bool = False
    paused: bool = False
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0
    total_seconds: float = 0.0
    playlist_mode: bool = False
    playlist_loop: bool = False
    playlist_position: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConnectionInfo:
    name: str
    host: str
    port: int
    connected_at: str

    @classmethod
    def now(cls, name: str, host: str, port: int) -> "ConnectionInfo":
        return cls(name=name, host=host, port=port, connected_at=datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LogEntry:
    level: str
    source: str
    message: str
    created_at: str

    @classmethod
    def now(cls, level: str, source: str, message: str) -> "LogEntry":
        return cls(level=level, source=source, message=message, created_at=datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VideoOutput:
    id: str
    label: str
    width: int | None = None
    height: int | None = None
    refresh_hz: float | None = None
    current_mode: str | None = None
    modes: list[str] = field(default_factory=list)
    primary: bool = False
    selected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlaylistItem:
    position: int
    clip_id: int
    clip_name: str
    duration_timecode: str
    loop_enabled: bool = False
    auto_advance: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlaylistSummary:
    id: int
    name: str
    is_active: bool = False
    item_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
