from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import Process
from pathlib import Path
from typing import Any

from app.core.config import AppConfig


class MPVController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.process: Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._request_id = 0
        self._selected_output_id: str | None = None
        self._current_video_format: str = config.default_video_format

    async def start(self) -> None:
        socket_path = Path(self.config.mpv_socket_path)
        if socket_path.exists():
            socket_path.unlink()
        extra_args: list[str] = []
        if self._selected_output_id:
            extra_args.append(f'--fs-screen={self._selected_output_id}')
        self.process = await asyncio.create_subprocess_exec(
            self.config.mpv_binary,
            '--idle=yes',
            '--fullscreen=yes',
            '--force-window=yes',
            '--keep-open=always',
            '--hwdec=auto-safe',
            f'--input-ipc-server={self.config.mpv_socket_path}',
            '--audio-display=no',
            *extra_args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(20):
            if socket_path.exists():
                break
            await asyncio.sleep(0.25)
        if socket_path.exists():
            self._reader, self._writer = await asyncio.open_unix_connection(self.config.mpv_socket_path)

    async def stop_process(self) -> None:
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()
        self.process = None

    async def is_available(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def command(self, command: list[Any]) -> dict[str, Any] | None:
        if not await self.is_available():
            return None
        self._request_id += 1
        payload = json.dumps({'command': command, 'request_id': self._request_id}).encode('utf-8') + b'\n'
        assert self._writer is not None
        self._writer.write(payload)
        await self._writer.drain()
        assert self._reader is not None
        response = await self._reader.readline()
        if not response:
            return None
        return json.loads(response.decode('utf-8'))

    async def play_file(self, path: str, loop: bool = False, is_vertical: bool = False) -> None:
        width, height = _target_dimensions(self._current_video_format)
        if is_vertical:
            lavfi = (
                f"lavfi=[split[main][bg];"
                f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},gblur=sigma=22[bg2];"
                f"[main]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                f"[bg2][fg]overlay=(W-w)/2:(H-h)/2]"
            )
            await self.command(['set_property', 'vf', lavfi])
        else:
            await self.command(['set_property', 'vf', ''])
        await self.command(['set_property', 'loop-file', 'inf' if loop else 'no'])
        await self.command(['loadfile', path, 'replace'])
        await self.command(['set_property', 'pause', False])

    async def stop(self) -> None:
        await self.command(['stop'])

    async def pause(self, enabled: bool = True) -> None:
        await self.command(['set_property', 'pause', enabled])

    async def set_volume(self, value: int) -> None:
        await self.command(['set_property', 'volume', value])

    async def set_mute(self, enabled: bool) -> None:
        await self.command(['set_property', 'mute', enabled])

    async def set_output(self, output_id: str) -> None:
        if output_id == self._selected_output_id:
            return
        self._selected_output_id = output_id
        if self.process is not None:
            await self.stop_process()
            await self.start()

    async def set_video_format(self, video_format: str) -> None:
        self._current_video_format = video_format


def _target_dimensions(video_format: str) -> tuple[int, int]:
    presets = {
        '1080p25': (1920, 1080),
        '1080p30': (1920, 1080),
        '1080p50': (1920, 1080),
        '1080p60': (1920, 1080),
    }
    return presets.get(video_format, (1920, 1080))
