from __future__ import annotations

import asyncio
import json
import os
import platform
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
        self._command_lock = asyncio.Lock()
        self._request_id = 0
        self._selected_output_id: str | None = None
        self._current_video_format: str = config.default_video_format
        self.last_error: str | None = None

    async def start(self) -> None:
        socket_path = Path(self.config.mpv_socket_path)
        if socket_path.exists():
            socket_path.unlink()
        log_path = Path(self.config.mpv_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('', encoding='utf-8')

        for profile_name, command in self._startup_profiles(log_path):
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            for _ in range(48):
                if socket_path.exists():
                    try:
                        self._reader, self._writer = await asyncio.open_unix_connection(self.config.mpv_socket_path)
                        self.last_error = None
                        return
                    except (ConnectionError, FileNotFoundError, OSError):
                        await asyncio.sleep(0.25)
                        continue
                if self.process.returncode is not None:
                    break
                await asyncio.sleep(0.25)
            await self.stop_process()
            self.last_error = self._build_start_error(profile_name, log_path)

        if not self.last_error:
            self.last_error = f'mpv IPC socket was not created at {self.config.mpv_socket_path}'

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
        return (
            self.process is not None
            and self.process.returncode is None
            and self._writer is not None
            and not self._writer.is_closing()
        )

    async def command(self, command: list[Any]) -> dict[str, Any] | None:
        if not await self.is_available():
            self.last_error = 'mpv is not available'
            return None
        async with self._command_lock:
            self._request_id += 1
            request_id = self._request_id
            payload = json.dumps({'command': command, 'request_id': request_id}).encode('utf-8') + b'\n'
            assert self._writer is not None
            try:
                self._writer.write(payload)
                await self._writer.drain()
                parsed = await self._read_response(request_id)
            except (ConnectionError, BrokenPipeError, OSError, RuntimeError) as exc:
                self.last_error = str(exc)
                return None
            if not parsed:
                return None
            self.last_error = None if parsed.get('error') == 'success' else str(parsed.get('error') or 'unknown mpv error')
            return parsed

    async def _command_ok(self, command: list[Any]) -> bool:
        response = await self.command(command)
        return bool(response and response.get('error') == 'success')

    async def play_file(self, path: str, loop: bool = False, is_vertical: bool = False) -> bool:
        width, height = _target_dimensions(self._current_video_format)
        if is_vertical:
            lavfi = (
                f"lavfi=[split[main][bg];"
                f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},gblur=sigma=22[bg2];"
                f"[main]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                f"[bg2][fg]overlay=(W-w)/2:(H-h)/2]"
            )
            if not await self._command_ok(['set_property', 'vf', lavfi]):
                return False
        else:
            if not await self._command_ok(['set_property', 'vf', '']):
                return False
        if not await self._command_ok(['set_property', 'loop-file', 'inf' if loop else 'no']):
            return False
        if not await self._command_ok(['loadfile', path, 'replace']):
            return False
        return await self._command_ok(['set_property', 'pause', False])

    async def stop(self) -> bool:
        return await self._command_ok(['stop'])

    async def pause(self, enabled: bool = True) -> bool:
        return await self._command_ok(['set_property', 'pause', enabled])

    async def set_volume(self, value: int) -> bool:
        return await self._command_ok(['set_property', 'volume', value])

    async def set_mute(self, enabled: bool) -> bool:
        return await self._command_ok(['set_property', 'mute', enabled])

    async def set_output(self, output_id: str) -> None:
        if output_id == self._selected_output_id:
            return
        self._selected_output_id = output_id
        if self.process is not None:
            await self.stop_process()
            await self.start()

    async def set_video_format(self, video_format: str) -> None:
        self._current_video_format = video_format

    async def _read_response(self, request_id: int) -> dict[str, Any] | None:
        assert self._reader is not None
        for _ in range(64):
            response = await self._reader.readline()
            if not response:
                self.last_error = 'mpv IPC returned an empty response'
                return None
            try:
                parsed = json.loads(response.decode('utf-8'))
            except json.JSONDecodeError as exc:
                self.last_error = f'invalid mpv IPC response: {exc}'
                return None
            if not isinstance(parsed, dict):
                continue
            incoming_request_id = parsed.get('request_id')
            if incoming_request_id is None and parsed.get('event'):
                continue
            if incoming_request_id != request_id:
                continue
            return parsed
        self.last_error = f'timed out waiting for mpv IPC response {request_id}'
        return None

    def _startup_profiles(self, log_path: Path) -> list[tuple[str, list[str]]]:
        base_args = [
            self.config.mpv_binary,
            '--idle=yes',
            '--fullscreen=yes',
            '--force-window=no',
            '--keep-open=no',
            '--audio-display=no',
            '--terminal=no',
            '--no-config',
            '--osc=no',
            '--load-scripts=no',
            '--osd-level=0',
            '--hwdec=auto-safe',
            f'--log-file={log_path}',
            f'--input-ipc-server={self.config.mpv_socket_path}',
        ]
        if self._selected_output_id and self._selected_output_id.isdigit():
            base_args.append(f'--fs-screen={self._selected_output_id}')
        drm_connector = None
        if self._selected_output_id and self._selected_output_id.startswith('drm:'):
            drm_connector = self._selected_output_id.split(':', 1)[1]

        profiles: list[tuple[str, list[str]]] = [('default', list(base_args))]
        platform_name = platform.system().lower()
        has_graphical_session = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

        if platform_name == 'linux' and not has_graphical_session:
            drm_args = [*base_args, '--vo=gpu', '--gpu-context=drm']
            if drm_connector:
                drm_args.append(f'--drm-connector={drm_connector}')
            profiles.insert(0, ('linux-drm', drm_args))
            profiles.append(('linux-gpu', [*base_args, '--vo=gpu']))

        return profiles

    def _build_start_error(self, profile_name: str, log_path: Path) -> str:
        tail = self._tail_file(log_path, line_count=20)
        if tail:
            return f'mpv startup failed ({profile_name}): {tail}'
        return f'mpv IPC socket was not created at {self.config.mpv_socket_path} ({profile_name})'

    def _tail_file(self, path: Path, line_count: int = 8) -> str:
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return ''
        if not lines:
            return ''
        return ' | '.join(lines[-line_count:])


def _target_dimensions(video_format: str) -> tuple[int, int]:
    presets = {
        '1080p25': (1920, 1080),
        '1080p30': (1920, 1080),
        '1080p50': (1920, 1080),
        '1080p60': (1920, 1080),
    }
    return presets.get(video_format, (1920, 1080))
