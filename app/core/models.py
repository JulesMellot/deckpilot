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
    media_kind: str = "video"
    is_vertical: bool = False
    thumbnail_path: str | None = None
    processing_state: str = "ready"
    loop_enabled: bool = False
    is_builtin: bool = False
    mark_in_seconds: float = 0.0
    mark_out_seconds: float = 0.0
    tags: str = ""
    has_audio_levels: bool = False
    # Which disk the file lives on ("Internal" or a USB drive's label), and
    # whether that disk is currently connected. Offline clips stay in the
    # library (metadata preserved) but cannot be fired until the drive returns.
    source: str = "Internal"
    available: bool = True
    # A network link (http/rtsp/...) played straight from mpv rather than a
    # file on disk. Remote clips have no /media preview and are never swept by
    # the disk sync.
    is_remote: bool = False

    def trim_bounds(self) -> tuple[float, float]:
        """Return the effective (in, out) playback window in absolute seconds.

        ``mark_out_seconds`` of 0 (or out of range) means "play to the end".
        Invalid windows (out <= in) fall back to the full clip duration.
        """
        duration = max(0.0, float(self.duration_seconds or 0.0))
        start = max(0.0, min(float(self.mark_in_seconds or 0.0), duration))
        end = float(self.mark_out_seconds or 0.0)
        if end <= 0.0 or end > duration:
            end = duration
        if end <= start:
            return 0.0, duration
        return start, end

    def has_marks(self) -> bool:
        start, end = self.trim_bounds()
        return start > 0.0 or end < max(0.0, float(self.duration_seconds or 0.0))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransportState:
    status: str = "stopped"
    speed: int = 0
    playback_speed_percent: int = 100
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
    mark_in_seconds: float = 0.0
    mark_out_seconds: float = 0.0
    trim_active: bool = False
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
    end_behavior: str = "next"

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
