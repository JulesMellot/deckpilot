from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import sys
from asyncio.subprocess import Process
from pathlib import Path
from typing import Any

from app.core.config import AppConfig

# A wedged mpv (GPU/decoder hang, common on a Pi) can keep its IPC socket open
# yet never answer. Without a ceiling, the readline below would block forever
# while holding the command lock and freeze every transport control. Bound the
# wait so a stuck command fails cleanly and the deck can recover mpv.
_IPC_READ_TIMEOUT = 10.0

_AUDIO_CARD_RE = re.compile(r'CARD=([^,]+)')

# Automatic ytdl format: the Pi's VideoCore decoder is rated 1080p30; 1080p60
# blacks out. Prefer exactly 1080p <=30fps (YouTube live), else the best
# <=720p at any fps (Twitch offers 1080p60/720p60/480p30 — a plain
# "<=1080p, <=30fps" filter would pick the tiny 480p30 over 720p60).
YTDL_FORMAT_AUTO = 'b[height=1080][fps<=31]/b[height<=720]/bv*[height<=720]+ba/b'
# The analog jack on a Pi is quiet because its ALSA mixer ships below unity.
# mpv's `volume` is software-only, so we lift the card's playback controls to
# 100% at startup; the slider then attenuates from a full-level signal.
_HARDWARE_MIXER_CONTROLS = ('PCM', 'Master', 'Headphone', 'Speaker', 'Digital')


class MPVController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.process: Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._command_lock = asyncio.Lock()
        self._request_id = 0
        self._selected_output_id: str | None = None
        self._selected_audio_device: str = (config.audio_device or 'auto').strip() or 'auto'
        self._current_video_format: str = config.default_video_format
        self._output_width: int | None = None
        self._output_height: int | None = None
        self._h264_hwdec: str | None = self._detect_h264_hwdec()
        # mpv keeps `speed` across loadfile, so we track the last value we set and
        # only push a 1x reset on a fresh load when the previous clip left it
        # off-speed — one fewer IPC round-trip on the common (1x) fire path.
        self._last_speed: float = 1.0
        # Same idea for ytdl-format: startup args set the automatic default,
        # per-clip caps override it, and we only push a change over IPC.
        self._last_ytdl_format: str = YTDL_FORMAT_AUTO
        self.last_error: str | None = None

    def _ipc_path(self) -> str:
        configured = self.config.mpv_socket_path
        if platform.system() == 'Windows' and not configured.startswith('\\\\.\\pipe\\'):
            return r'\\.\pipe\deckpilot-mpv'
        return configured

    def _ipc_is_pipe(self) -> bool:
        return self._ipc_path().startswith('\\\\.\\pipe\\')

    async def _open_ipc(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        ipc_path = self._ipc_path()
        if self._ipc_is_pipe():
            # Windows named pipe via the proactor event loop.
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.create_pipe_connection(lambda: protocol, ipc_path)  # type: ignore[attr-defined]
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            return reader, writer
        return await asyncio.open_unix_connection(ipc_path)

    async def start(self) -> None:
        if not self._ipc_is_pipe():
            socket_path = Path(self._ipc_path())
            if socket_path.exists():
                socket_path.unlink()
        log_path = Path(self.config.mpv_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('', encoding='utf-8')

        for profile_name, command in self._startup_profiles(log_path):
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self.process = process
            for _ in range(48):
                try:
                    self._reader, self._writer = await self._open_ipc()
                    self.last_error = None
                    # A fresh mpv process starts at 1x; keep the trackers in sync.
                    self._last_speed = 1.0
                    self._last_ytdl_format = YTDL_FORMAT_AUTO
                    await self._maximize_hardware_mixer()
                    return
                except (ConnectionError, FileNotFoundError, OSError):
                    pass
                if process.returncode is not None:
                    break
                await asyncio.sleep(0.25)
            await self.stop_process()
            self.last_error = self._build_start_error(profile_name, log_path)

        if not self.last_error:
            self.last_error = f'mpv IPC endpoint was not created at {self._ipc_path()}'

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
        process = self.process
        writer = self._writer
        return (
            process is not None
            and process.returncode is None
            and writer is not None
            and not writer.is_closing()
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

    @staticmethod
    def _ytdl_format_for(max_height: int) -> str:
        # An explicit operator cap wins over the automatic choice — including
        # 60 fps variants (their call; 1080p60 exceeds the Pi 3's decoder).
        if max_height:
            return f'b[height<={max_height}]/bv*[height<={max_height}]+ba/b'
        return YTDL_FORMAT_AUTO

    async def _apply_ytdl_format(self, max_height: int | None) -> None:
        # Only network links carry a value (None for local files: the option is
        # unused there, and skipping the IPC round-trip keeps fires cheap).
        if max_height is None:
            return
        desired = self._ytdl_format_for(int(max_height))
        if desired != self._last_ytdl_format:
            await self._command_ok(['set_property', 'ytdl-format', desired])
            self._last_ytdl_format = desired

    async def play_file(self, path: str, loop: bool = False, is_vertical: bool = False, start: float = 0.0, codec: str | None = None,
                        remote_max_height: int | None = None) -> bool:
        # Pick the decoder for this clip's codec before loading: H.264 gets the
        # Pi's hardware path, everything else the default. Set per-load because a
        # previous clip may have left a different hwdec in place.
        await self._command_ok(['set_property', 'hwdec', self._hwdec_for_codec(codec)])
        await self._apply_ytdl_format(remote_max_height)
        # Only reset to 1x when the last clip left it off-speed (mpv keeps speed
        # across loadfile); skipping the no-op saves an IPC round-trip on a fire.
        if not await self._reset_speed():
            return False
        # Load paused so we can seek to the in-mark before the first frame is shown.
        if not await self._command_ok(['set_property', 'pause', True]):
            return False
        if not await self._command_ok(['loadfile', path, 'replace']):
            return False
        if not await self.set_loop(loop):
            return False
        if start > 0:
            await self.seek_absolute(start)
        return await self._command_ok(['set_property', 'pause', False])

    async def cue_file(self, path: str, loop: bool = False, is_vertical: bool = False, start: float = 0.0, codec: str | None = None,
                       remote_max_height: int | None = None) -> bool:
        await self._command_ok(['set_property', 'hwdec', self._hwdec_for_codec(codec)])
        await self._apply_ytdl_format(remote_max_height)
        if not await self._reset_speed():
            return False
        if not await self._command_ok(['set_property', 'pause', True]):
            return False
        if not await self._command_ok(['loadfile', path, 'replace']):
            return False
        if not await self.set_loop(loop):
            return False
        if start > 0:
            await self.seek_absolute(start)
        return True

    async def show_standby(self, path: str) -> bool:
        # image-display-duration=inf is set at startup, so the slate is held
        # indefinitely instead of advancing past it.
        if not await self._command_ok(['loadfile', path, 'replace']):
            return False
        if not await self.set_loop(False):
            return False
        return await self._command_ok(['set_property', 'pause', False])

    async def stop(self) -> bool:
        return await self._command_ok(['stop'])

    async def pause(self, enabled: bool = True) -> bool:
        return await self._command_ok(['set_property', 'pause', enabled])

    async def seek_absolute(self, seconds: float) -> bool:
        return await self._command_ok(['set_property', 'time-pos', max(0.0, float(seconds))])

    async def set_loop(self, enabled: bool) -> bool:
        return await self._command_ok(['set_property', 'loop-file', 'inf' if enabled else 'no'])

    async def set_speed(self, factor: float) -> bool:
        ok = await self._command_ok(['set_property', 'speed', float(factor)])
        if ok:
            self._last_speed = float(factor)
        return ok

    async def _reset_speed(self) -> bool:
        """Return playback to 1x before a load, but only when the previous clip
        left it off-speed. mpv carries `speed` across loadfile, so a fresh fire
        after a normal-speed clip needs no IPC round-trip here."""
        if self._last_speed == 1.0:
            return True
        return await self.set_speed(1.0)

    async def set_volume(self, value: int) -> bool:
        return await self._command_ok(['set_property', 'volume', value])

    async def set_mute(self, enabled: bool) -> bool:
        return await self._command_ok(['set_property', 'mute', enabled])

    @property
    def selected_audio_device(self) -> str:
        return self._selected_audio_device

    async def list_audio_devices(self) -> list[dict[str, str]]:
        response = await self.command(['get_property', 'audio-device-list'])
        if not response or response.get('error') != 'success':
            return []
        devices: list[dict[str, str]] = []
        for item in response.get('data') or []:
            if not isinstance(item, dict) or not item.get('name'):
                continue
            name = str(item['name'])
            devices.append({'name': name, 'description': str(item.get('description') or name)})
        return devices

    async def set_audio_device(self, device: str) -> bool:
        self._selected_audio_device = (device or 'auto').strip() or 'auto'
        await self._maximize_hardware_mixer()
        if not await self.is_available():
            # Remembered anyway: the next mpv start picks it up via --audio-device.
            return True
        return await self._command_ok(['set_property', 'audio-device', self._selected_audio_device])

    async def _maximize_hardware_mixer(self) -> None:
        """Lift the selected card's ALSA playback controls to full level so the
        software slider is not fighting a half-open hardware mixer."""
        if platform.system().lower() != 'linux':
            return
        match = _AUDIO_CARD_RE.search(self._selected_audio_device)
        if not match:
            return
        card = match.group(1)
        for control in _HARDWARE_MIXER_CONTROLS:
            try:
                process = await asyncio.create_subprocess_exec(
                    'amixer', '-c', card, 'sset', control, '100%', 'unmute',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (FileNotFoundError, OSError):
                return  # amixer absent: nothing more to try
            # A missing control just returns non-zero — harmless, move on.
            await process.wait()

    async def set_output(self, output_id: str) -> None:
        if output_id == self._selected_output_id:
            return
        self._selected_output_id = output_id
        if self.process is not None:
            await self.stop_process()
            await self.start()

    async def set_video_format(self, video_format: str) -> None:
        self._current_video_format = video_format

    async def set_output_geometry(self, width: int | None, height: int | None) -> None:
        self._output_width = width if width and width > 0 else None
        self._output_height = height if height and height > 0 else None

    async def _read_response(self, request_id: int) -> dict[str, Any] | None:
        assert self._reader is not None
        for _ in range(64):
            try:
                response = await asyncio.wait_for(self._reader.readline(), _IPC_READ_TIMEOUT)
            except asyncio.TimeoutError:
                self.last_error = f'mpv IPC timed out waiting for response {request_id}'
                return None
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

    def _hwdec_mode(self) -> str:
        # mpv tolerates an unknown hwdec (logs "Unsupported hwdec" and falls
        # back to software), so a Pi value like "v4l2m2m-copy" stays harmless on
        # other hosts. An empty config still gets the safe cross-platform pick.
        return (self.config.mpv_hwdec or '').strip() or 'auto-safe'

    def _detect_h264_hwdec(self) -> str | None:
        # An explicit config wins; otherwise auto-detect the Pi's VideoCore
        # H.264 decoder. On Pi OS the bcm2835-codec exposes it at /dev/video10
        # and mpv reaches it through ffmpeg's v4l2m2m wrapper. `auto-safe` never
        # selects it, so H.264 clips would otherwise software-decode and stutter.
        configured = (self.config.mpv_hwdec_h264 or '').strip()
        if configured:
            return configured
        if platform.system().lower() == 'linux' and Path('/dev/video10').exists():
            # dmabuf-wayland needs zero-copy frames (drm_prime), so under a
            # compositor use plain v4l2m2m; the direct-DRM/GL path cannot import
            # those and needs the -copy variant instead.
            if (self.config.mpv_compositor or '').strip():
                return 'v4l2m2m'
            return 'v4l2m2m-copy'
        return None

    def _hwdec_for_codec(self, codec: str | None) -> str:
        # H.264 gets the dedicated hardware path when one was detected; anything
        # else (HEVC/VP9/images/…) falls back to the general default, which the
        # Pi has no hardware block for anyway. 'unknown' means a network link
        # whose page ffprobe could not read (Twitch, YouTube live…): those
        # sources are H.264 in practice, and software decode blacks out the
        # video on a Pi 3 — assume H.264; mpv falls back by itself if not.
        if self._h264_hwdec and (codec or '').strip().lower() in ('h264', 'unknown'):
            return self._h264_hwdec
        return self._hwdec_mode()

    def _startup_profiles(self, log_path: Path) -> list[tuple[str, list[str]]]:
        base_args = [
            self.config.mpv_binary,
            '--idle=yes',
            '--fullscreen=yes',
            '--force-window=no',
            # Hold the last frame at EOF instead of flashing the idle screen; the
            # deck controller decides what happens next (stop / advance / hold).
            '--keep-open=always',
            # Hold stills indefinitely; the deck controller decides when to
            # advance. Set once here instead of per-load (mpv keeps it across
            # loadfile), saving an IPC round-trip on every clip fire.
            '--image-display-duration=inf',
            '--audio-display=no',
            '--terminal=no',
            '--no-config',
            '--osc=no',
            '--load-scripts=no',
            '--osd-level=0',
            # Never show the pointer on the program output. mpv is fullscreen, so
            # under cage/Wayland it asks the compositor to hide the cursor over
            # its surface; on direct DRM there is no cursor anyway. Without this,
            # cage draws its default pointer over the video 24/7.
            '--cursor-autohide=always',
            '--no-input-cursor',
            f'--hwdec={self._hwdec_mode()}',
            # Bound the demuxer cache: mpv defaults to ~150 MiB forward cache,
            # which starves a 1 GB Pi. Local SD/USB reads do not need it.
            '--demuxer-max-bytes=48MiB',
            '--demuxer-max-back-bytes=16MiB',
            # Plain resampling at off-speeds instead of scaletempo: cheaper on
            # Pi-class CPUs and the natural pitch shift suits replay workflows.
            '--audio-pitch-correction=no',
            f'--log-file={log_path}',
            f'--input-ipc-server={self._ipc_path()}',
            # Live page links (Twitch, YouTube live…) are resolved at fire time
            # by mpv's built-in ytdl hook; see _ytdl_format_for(). Clips with an
            # operator-chosen resolution cap override this per load.
            f'--ytdl-format={YTDL_FORMAT_AUTO}',
        ]
        venv_ytdlp = Path(sys.executable).parent / 'yt-dlp'
        if venv_ytdlp.exists():
            # Point the hook at the venv's fresh yt-dlp: the Debian-packaged
            # one found in PATH is years old and broken against YouTube/Twitch.
            base_args.append(f'--script-opts=ytdl_hook-ytdl_path={venv_ytdlp}')
        if self._selected_audio_device != 'auto':
            base_args.append(f'--audio-device={self._selected_audio_device}')
        if self._selected_output_id and self._selected_output_id.isdigit():
            base_args.append(f'--fs-screen={self._selected_output_id}')
        drm_connector = None
        if self._selected_output_id and self._selected_output_id.startswith('drm:'):
            drm_connector = self._selected_output_id.split(':', 1)[1]

        compositor = (self.config.mpv_compositor or '').strip()
        if compositor:
            # mpv runs as a client of a nested Wayland compositor (e.g. cage) and
            # outputs via dmabuf-wayland, which the compositor scans out on a
            # hardware plane. On a Pi 3 this is the only fluid 1080p path: the
            # direct DRM overlay is rejected by the VC4 (atomic commit -22) and
            # the GL renderer drops ~60% of frames at 1080p. `cage -- mpv ...`
            # keeps mpv as the child, so the IPC socket still works.
            wayland_args = [*compositor.split(), '--', *base_args, '--vo=dmabuf-wayland']
            return [('compositor', wayland_args)]

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
        return f'mpv IPC endpoint was not created at {self._ipc_path()} ({profile_name})'

    def _tail_file(self, path: Path, line_count: int = 8) -> str:
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return ''
        if not lines:
            return ''
        return ' | '.join(lines[-line_count:])
