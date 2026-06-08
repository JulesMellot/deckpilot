from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class AppConfig:
    app_name: str = "DeckPilot"
    protocol_model: str = "Blackmagic HyperDeck Studio Mini"
    protocol_version: str = "1.11"
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    hyperdeck_host: str = "0.0.0.0"
    hyperdeck_port: int = 9993
    clips_dir: str = "/home/pi/pideck/clips"
    data_dir: str = "/home/pi/pideck/data"
    db_path: str = "/home/pi/pideck/data/pideck.db"
    thumbnails_dir: str = "/home/pi/pideck/data/thumbnails"
    mpv_socket_path: str = "/tmp/pideck-mpv.sock"
    mpv_log_path: str = "/home/pi/pideck/data/mpv.log"
    mpv_binary: str = "mpv"
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    default_video_format: str = "1080p25"
    default_framerate: float = 25.0
    ws_tick_seconds: float = 1.0
    log_buffer_size: int = 200
    allowed_upload_extensions: list[str] = field(default_factory=lambda: [".mp4", ".mov", ".mkv"])
    media_enrichment_workers: int = field(default_factory=lambda: max(1, min(4, os.cpu_count() or 2)))

    def ensure_directories(self) -> None:
        Path(self.clips_dir).mkdir(parents=True, exist_ok=True)
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.thumbnails_dir).mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _merge_dict(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(target)
    merged.update({k: v for k, v in source.items() if v is not None})
    return merged


def load_config() -> AppConfig:
    defaults = AppConfig()
    config_path = os.environ.get("PIDECK_CONFIG", str(Path.cwd() / "config.json"))
    raw = defaults.to_dict()

    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as handle:
            raw = _merge_dict(raw, json.load(handle))

    env_overrides = {
        "http_host": os.environ.get("PIDECK_HTTP_HOST"),
        "http_port": int(os.environ["PIDECK_HTTP_PORT"]) if os.environ.get("PIDECK_HTTP_PORT") else None,
        "hyperdeck_host": os.environ.get("PIDECK_HYPERDECK_HOST"),
        "hyperdeck_port": int(os.environ["PIDECK_HYPERDECK_PORT"]) if os.environ.get("PIDECK_HYPERDECK_PORT") else None,
        "clips_dir": os.environ.get("PIDECK_CLIPS_DIR"),
        "data_dir": os.environ.get("PIDECK_DATA_DIR"),
        "db_path": os.environ.get("PIDECK_DB_PATH"),
        "mpv_log_path": os.environ.get("PIDECK_MPV_LOG_PATH"),
        "default_video_format": os.environ.get("PIDECK_VIDEO_FORMAT"),
        "media_enrichment_workers": int(os.environ["PIDECK_MEDIA_ENRICHMENT_WORKERS"]) if os.environ.get("PIDECK_MEDIA_ENRICHMENT_WORKERS") else None,
    }
    raw = _merge_dict(raw, env_overrides)

    if not raw.get("mpv_log_path"):
        data_dir = raw.get("data_dir") or defaults.data_dir
        raw["mpv_log_path"] = str(Path(data_dir) / "mpv.log")

    config = AppConfig(**raw)
    config.ensure_directories()
    return config
