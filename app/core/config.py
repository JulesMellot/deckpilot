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
    # mpv --hwdec mode. "auto-safe" is the right cross-platform default (picks
    # videotoolbox/vaapi/etc. only when known-good). It does NOT engage the
    # Raspberry Pi's V4L2 H.264 decoder, so a Pi software-decodes 1080p and
    # drops frames; set "v4l2m2m-copy" on a Pi to use the hardware decoder.
    mpv_hwdec: str = "auto-safe"
    # hwdec used specifically for H.264 clips. Empty = auto-detect: on a Pi
    # (Linux + /dev/video10) it resolves to "v4l2m2m-copy" to drive the
    # VideoCore H.264 decoder, otherwise it falls back to `mpv_hwdec`. Set it
    # explicitly (e.g. "drm" or "no") to override the auto-detection. When
    # `mpv_compositor` is set the auto-detect picks zero-copy "v4l2m2m" instead.
    mpv_hwdec_h264: str = ""
    # Optional nested Wayland compositor that wraps mpv (e.g. "cage"). Empty =
    # launch mpv directly on DRM/KMS. On a Pi 3 the direct overlay is rejected
    # by the VC4 and the GL renderer drops frames at 1080p; running mpv as a
    # client of a compositor with --vo=dmabuf-wayland scans the decoded frame
    # out on a hardware plane, which is the only fluid 1080p path. The value is
    # split on spaces, so flags are allowed (e.g. "cage -d").
    mpv_compositor: str = ""
    # Conform imported video clips to the project format at import time: scale +
    # letterbox to `default_video_format`'s resolution and re-encode to H.264, so
    # every clip plays 1:1 full screen. Required on hardware that cannot scale
    # video live (e.g. Pi 3 + dmabuf-wayland, where the VC4 has no plane scaler).
    # Clips already H.264 at the target resolution pass through untouched.
    conform_clips: bool = False
    # Encoder for the conform pass. The Pi's hardware H.264 encoder keeps it near
    # real time; the code falls back to libx264 if this encoder fails.
    conform_encoder: str = "h264_v4l2m2m"
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    default_video_format: str = "1080p25"
    default_framerate: float = 25.0
    # mpv audio device name ("auto", "alsa/sysdefault:CARD=vc4hdmi0", ...);
    # lets the sound leave through HDMI or the headphone jack independently
    # of the selected video output.
    audio_device: str = "auto"
    ws_tick_seconds: float = 1.0
    log_buffer_size: int = 200
    allowed_upload_extensions: list[str] = field(default_factory=lambda: [".mp4", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".gif"])
    # Capped at 2 by default: a playout deck must keep headroom for mpv even
    # during a large import (override with PIDECK_MEDIA_ENRICHMENT_WORKERS).
    media_enrichment_workers: int = field(default_factory=lambda: max(1, min(2, os.cpu_count() or 2)))
    default_image_duration_seconds: float = 10.0
    watch_folder_seconds: float = 5.0
    config_path: str = ""

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


def _env_bool(name: str) -> bool | None:
    """Parse a boolean env var; None when unset so it doesn't override config."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
        "audio_device": os.environ.get("PIDECK_AUDIO_DEVICE"),
        "mpv_hwdec": os.environ.get("PIDECK_MPV_HWDEC"),
        "mpv_hwdec_h264": os.environ.get("PIDECK_MPV_HWDEC_H264"),
        "mpv_compositor": os.environ.get("PIDECK_MPV_COMPOSITOR"),
        "conform_clips": _env_bool("PIDECK_CONFORM_CLIPS"),
        "conform_encoder": os.environ.get("PIDECK_CONFORM_ENCODER"),
        "media_enrichment_workers": int(os.environ["PIDECK_MEDIA_ENRICHMENT_WORKERS"]) if os.environ.get("PIDECK_MEDIA_ENRICHMENT_WORKERS") else None,
        "default_image_duration_seconds": float(os.environ["PIDECK_DEFAULT_IMAGE_DURATION_SECONDS"]) if os.environ.get("PIDECK_DEFAULT_IMAGE_DURATION_SECONDS") else None,
        "watch_folder_seconds": float(os.environ["PIDECK_WATCH_FOLDER_SECONDS"]) if os.environ.get("PIDECK_WATCH_FOLDER_SECONDS") else None,
    }
    raw = _merge_dict(raw, env_overrides)

    if not raw.get("mpv_log_path"):
        data_dir = raw.get("data_dir") or defaults.data_dir
        raw["mpv_log_path"] = str(Path(data_dir) / "mpv.log")

    raw["allowed_upload_extensions"] = _migrate_upload_extensions(raw.get("allowed_upload_extensions"))

    raw.pop("config_path", None)
    config = AppConfig(**raw)
    config.config_path = config_path
    config.ensure_directories()
    return config


def _migrate_upload_extensions(value: Any) -> list[str]:
    defaults = AppConfig().allowed_upload_extensions
    if not isinstance(value, list) or not value:
        return defaults
    normalized = []
    for item in value:
        text = str(item).strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = f".{text}"
        normalized.append(text)
    # config.json files written before still support pinned the video-only
    # list; extend them so image uploads work after an update.
    if set(normalized) == {".mp4", ".mov", ".mkv"}:
        return defaults
    return normalized or defaults
