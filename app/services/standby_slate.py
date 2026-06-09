from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from app.core.config import AppConfig
from app.services.network_info import NetworkInfoService

# Candidate font files across the platforms DeckPilot runs on. The first one
# that exists is used; if none are found we fall back to fontconfig's default.
_FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/Library/Fonts/Arial.ttf',
)


class StandbySlateService:
    """Renders the idle/standby slate shown on the playout output.

    The slate is a grey radial-gradient background with the deck name and the
    current network targets, generated with ffmpeg. It is regenerated whenever
    the detected network info changes so a DHCP lease change is reflected on
    the HDMI output.
    """

    def __init__(self, config: AppConfig, network_info: NetworkInfoService) -> None:
        self.config = config
        self.network_info = network_info
        self.output_path = Path(config.data_dir) / 'standby_slate.png'
        self._font = self._resolve_font()
        self._signature: str | None = None

    def _resolve_font(self) -> str | None:
        for candidate in _FONT_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return None

    async def ensure_slate(self) -> str | None:
        info = await self.network_info.snapshot()
        signature = self._signature_for(info)
        if self._signature == signature and self.output_path.exists():
            return str(self.output_path)
        ok = await asyncio.to_thread(self._render_sync, info)
        if not ok:
            return None
        self._signature = signature
        return str(self.output_path)

    def _signature_for(self, info: dict) -> str:
        return '|'.join(
            [
                self.config.app_name,
                info.get('primary_ip', ''),
                str(info.get('http_port', '')),
                str(info.get('hyperdeck_port', '')),
            ]
        )

    def _render_sync(self, info: dict) -> bool:
        if not shutil.which(self.config.ffmpeg_binary):
            return False
        primary_ip = info.get('primary_ip', '127.0.0.1')
        http_url = info.get('http_url', f"http://{primary_ip}")
        hyperdeck_target = info.get('hyperdeck_target', primary_ip)
        title = self.config.app_name or 'DeckPilot'

        font = f"fontfile='{self._font}':" if self._font else ''
        gradient = (
            "geq=lum='160-78*hypot((X-W/2)/(W/2)\\,(Y-H/2)/(H/2))':cb=128:cr=128,format=yuv420p"
        )
        layers = [
            (title, 'ffffff', 170, '(h/2)-235'),
            ('STANDBY', 'c8c8c8', 38, '(h/2)-40'),
            (primary_ip, 'ffffff', 74, '(h/2)+35'),
            (f'WEB {http_url}', 'dcdcdc', 36, '(h/2)+150'),
            (f'HYPERDECK {hyperdeck_target}', 'dcdcdc', 36, '(h/2)+200'),
        ]
        draw = ','.join(
            f"drawtext={font}text='{self._escape(text)}':fontcolor=0x{color}:"
            f"fontsize={size}:x=(w-text_w)/2:y={y}"
            for text, color, size, y in layers
        )
        vf = f'{gradient},{draw}'
        cmd = [
            self.config.ffmpeg_binary,
            '-y',
            '-hide_banner',
            '-loglevel',
            'error',
            '-f',
            'lavfi',
            '-i',
            'color=c=black:s=1920x1080',
            '-vf',
            vf,
            '-frames:v',
            '1',
            str(self.output_path),
        ]
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0 and self.output_path.exists()

    @staticmethod
    def _escape(text: str) -> str:
        # Escape characters that are special inside an ffmpeg filtergraph value.
        return (
            text.replace('\\', '\\\\')
            .replace(':', '\\:')
            .replace("'", "\\'")
            .replace('%', '\\%')
        )
