from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from typing import Any, Dict

from app.core.config import AppConfig
from app.core.state import AppState
from app.media.clip_store import ClipStore, seconds_to_timecode
from app.media.playlist_store import PlaylistStore
from app.player.mpv_controller import MPVController
from app.services.network_info import NetworkInfoService
from app.services.output_manager import OutputManager


class DeckController:
    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        clip_store: ClipStore,
        playlist_store: PlaylistStore,
        output_manager: OutputManager,
        network_info: NetworkInfoService,
        player: MPVController,
    ) -> None:
        self.config = config
        self.state = state
        self.clip_store = clip_store
        self.playlist_store = playlist_store
        self.output_manager = output_manager
        self.network_info = network_info
        self.player = player
        self.current_clip_id: int | None = None
        self._play_started_at: float | None = None
        self._pause_started_at: float | None = None
        self._accumulated_pause_seconds: float = 0.0
        self._ticker_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._volume: int = 100
        self._muted: bool = False
        self._playlist_mode = False
        self._playlist_loop = False
        self._last_clip_sync_at: float | None = None
        self._last_error: str | None = None
        self._last_error_key: str | None = None
        self._recovering_player = False

    async def start(self) -> None:
        self._ticker_task = asyncio.create_task(self._ticker())
        self._health_task = asyncio.create_task(self._health_reporter())

    async def stop(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker_task
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task

    async def list_clips(self):
        return await self.clip_store.list_clips()

    async def refresh_clips(self) -> None:
        await self.clip_store.sync_with_disk()
        await self.playlist_store.sync_active_playlist_from_clips()
        clips = await self.clip_store.list_clips()
        self._last_clip_sync_at = time.time()
        await self.state.publish('clips', {'clips': [clip.to_dict() for clip in clips]})
        await self.state.publish('playlist', await self.playlist_store.get_active_playlist())
        await self.state.publish('slot', await self.slot_snapshot())
        await self._publish_health()

    async def goto_clip(self, clip_id: int) -> bool:
        clip = await self.clip_store.get_clip(clip_id)
        if not clip:
            return False
        if not clip.filepath:
            await self._report_error('playback', f'Cannot cue clip "{clip.name}": missing file path.')
            await self._publish_health()
            return False
        if not await self._ensure_player_ready():
            await self._report_error('player', f'Player unavailable for cue: {self.player.last_error or "startup failed"}')
            await self._publish_health()
            return False
        if not await self.player.cue_file(clip.filepath, is_vertical=clip.is_vertical):
            await self._report_error('player', f'Cue failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
            await self._publish_health()
            return False
        self.current_clip_id = clip.deck_id
        self._play_started_at = time.monotonic()
        self._pause_started_at = self._play_started_at
        self._accumulated_pause_seconds = 0.0
        await self.state.set_transport(
            status='stopped',
            speed=0,
            clip_id=clip.deck_id,
            timecode='00:00:00:00',
            display_timecode='00:00:00:00',
            total_seconds=clip.duration_seconds,
            remaining_seconds=clip.duration_seconds,
            elapsed_seconds=0.0,
            video_format=self.state.transport.video_format,
            loop=clip.loop_enabled,
            paused=True,
        )
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def play(self, clip_id: int | None = None, loop: bool | None = None, single_clip: bool | None = None) -> bool:
        target_clip_id = clip_id or self.current_clip_id or 1
        clip = await self.clip_store.get_clip(target_clip_id)
        if not clip:
            await self._report_error('playback', f'Cannot play clip {target_clip_id}: clip not found.')
            await self._publish_health()
            return False
        if not clip.filepath:
            await self._report_error('playback', f'Cannot play clip "{clip.name}": missing file path.')
            await self._publish_health()
            return False
        self.current_clip_id = clip.deck_id
        use_loop = clip.loop_enabled if loop is None else loop
        started = await self._start_clip_playback(clip, use_loop)
        if not started:
            return False
        self._play_started_at = time.monotonic()
        self._pause_started_at = None
        self._accumulated_pause_seconds = 0.0
        await self.state.set_transport(
            status='play',
            speed=100,
            clip_id=clip.deck_id,
            loop=use_loop,
            single_clip=bool(single_clip),
            paused=False,
            total_seconds=clip.duration_seconds,
            remaining_seconds=clip.duration_seconds,
            elapsed_seconds=0.0,
            video_format=self.state.transport.video_format,
            playlist_mode=self._playlist_mode,
            playlist_loop=self._playlist_loop,
            playlist_position=await self._playlist_position_for_clip(clip.deck_id),
        )
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def pause(self) -> None:
        if not await self.player.pause(True):
            await self._report_error('player', f'Pause failed: {self.player.last_error or "unknown player error"}')
            await self._publish_health()
            return
        if self._pause_started_at is None:
            self._pause_started_at = time.monotonic()
        await self.state.set_transport(status='stopped', paused=True, speed=0)

    async def resume(self) -> None:
        if not await self.player.pause(False):
            await self._report_error('player', f'Resume failed: {self.player.last_error or "unknown player error"}')
            await self._publish_health()
            return
        if self._pause_started_at is not None:
            self._accumulated_pause_seconds += time.monotonic() - self._pause_started_at
            self._pause_started_at = None
        await self.state.set_transport(status='play', paused=False, speed=100)

    async def stop_playback(self) -> None:
        if await self.player.is_available():
            if not await self.player.stop():
                await self._report_error('player', f'Stop failed: {self.player.last_error or "unknown player error"}')
            await self.player.stop_process()
        self._play_started_at = None
        self._pause_started_at = None
        self._accumulated_pause_seconds = 0.0
        self._playlist_mode = False
        await self.state.set_transport(
            status='stopped',
            speed=0,
            paused=False,
            elapsed_seconds=0.0,
            remaining_seconds=self.state.transport.total_seconds,
            timecode='00:00:00:00',
            display_timecode='00:00:00:00',
            playlist_mode=False,
        )
        await self._publish_health()

    async def cut_to_black(self) -> bool:
        clips = await self.clip_store.list_clips()
        black = next((clip for clip in clips if clip.name.lower() == 'black'), None)
        if not black:
            await self.stop_playback()
            return True
        return await self.play(black.deck_id, loop=True, single_clip=False)

    async def rename_clip(self, deck_id: int, name: str) -> None:
        await self.clip_store.rename_clip(deck_id, name)
        await self.refresh_clips()

    async def set_loop(self, deck_id: int, enabled: bool) -> None:
        updated = await self.clip_store.set_loop(deck_id, enabled)
        if updated and self.current_clip_id == deck_id:
            await self.state.set_transport(loop=enabled)
        await self.refresh_clips()

    async def delete_clip(self, deck_id: int) -> None:
        if self.current_clip_id == deck_id:
            await self.stop_playback()
            self.current_clip_id = None
        await self.clip_store.delete_clip(deck_id)
        await self.refresh_clips()

    async def reorder(self, deck_ids: list[int]) -> None:
        await self.clip_store.reorder(deck_ids)
        await self.playlist_store.reorder_active_playlist(deck_ids)
        await self.refresh_clips()

    async def set_preview_enabled(self, enabled: bool) -> None:
        await self.state.set_preview_enabled(enabled)

    async def set_remote_enabled(self, enabled: bool) -> None:
        await self.state.set_remote_enabled(enabled)

    async def set_video_format(self, video_format: str) -> None:
        await self.player.set_video_format(video_format)
        await self.state.set_transport(video_format=video_format)
        await self.state.publish('slot', await self.slot_snapshot())
        await self._publish_health()

    async def play_playlist(self, loop: bool = False) -> bool:
        playlist = await self.playlist_store.get_active_playlist()
        items = playlist.get('items', [])
        if not items:
            return False
        return await self.play_playlist_from_position(1, loop=loop)

    async def set_playlist_loop(self, enabled: bool) -> None:
        self._playlist_loop = enabled
        await self.state.set_transport(playlist_loop=enabled, playlist_mode=self._playlist_mode)

    async def play_single_clip(self, clip_id: int) -> bool:
        self._playlist_mode = False
        return await self.play(clip_id=clip_id, loop=None, single_clip=True)

    async def play_next_playlist_item(self) -> bool:
        playlist = await self.playlist_store.get_active_playlist()
        items = playlist.get('items', [])
        if not items:
            return False
        current_position = await self._playlist_position_for_clip(self.current_clip_id or 0)
        if current_position <= 0:
            next_item = items[0]
        elif current_position >= len(items):
            if not self._playlist_loop:
                await self.stop_playback()
                return False
            next_item = items[0]
        else:
            next_item = items[current_position]
        self._playlist_mode = True
        return await self.play(clip_id=next_item['clip_id'], loop=False, single_clip=False)

    async def play_playlist_from_position(self, position: int, loop: bool | None = None) -> bool:
        playlist = await self.playlist_store.get_active_playlist()
        items = playlist.get('items', [])
        if not items:
            return False
        index = max(1, min(position, len(items))) - 1
        self._playlist_mode = True
        if loop is not None:
            self._playlist_loop = loop
        return await self.play(clip_id=items[index]['clip_id'], loop=False, single_clip=False)

    async def list_outputs(self) -> list[dict[str, Any]]:
        outputs = await self.output_manager.list_outputs()
        return [item.to_dict() for item in outputs]

    async def select_output(self, output_id: str) -> None:
        await self.output_manager.set_selected_output(output_id)
        selected_output = await self.output_manager.get_selected_output()
        await self.player.set_output_geometry(
            selected_output.width if selected_output else None,
            selected_output.height if selected_output else None,
        )
        await self.player.set_output(output_id)
        await self.state.publish('outputs', {'outputs': await self.list_outputs()})
        await self._publish_health()

    async def playlist_snapshot(self) -> Dict[str, Any]:
        return await self.playlist_store.get_active_playlist()

    async def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(volume, 100))
        if await self.player.is_available() and not await self.player.set_volume(self._volume):
            await self._report_error('player', f'Volume update failed: {self.player.last_error or "unknown player error"}')
        await self.state.publish('audio', {'volume': self._volume, 'muted': self._muted})
        await self._publish_health()

    async def set_mute(self, enabled: bool) -> None:
        self._muted = enabled
        if await self.player.is_available() and not await self.player.set_mute(enabled):
            await self._report_error('player', f'Mute update failed: {self.player.last_error or "unknown player error"}')
        await self.state.publish('audio', {'volume': self._volume, 'muted': self._muted})
        await self._publish_health()

    def audio_snapshot(self) -> Dict[str, Any]:
        return {'volume': self._volume, 'muted': self._muted}

    async def slot_snapshot(self) -> Dict[str, Any]:
        clips = await self.clip_store.list_clips()
        return {
            'slot_id': 1,
            'status': 'mounted',
            'volume_name': self.config.app_name,
            'clip_count': len(clips),
            'video_format': self.state.transport.video_format,
        }

    async def health_snapshot(self) -> Dict[str, Any]:
        clips = await self.clip_store.list_clips()
        outputs = await self.output_manager.list_outputs()
        selected_output = next((item for item in outputs if item.selected), None)
        free_bytes = 0
        total_bytes = 0
        try:
            usage = shutil.disk_usage(self.config.data_dir)
            free_bytes = usage.free
            total_bytes = usage.total
        except OSError:
            pass
        player_available = await self.player.is_available()
        return {
            'player_available': player_available,
            'player_error': self.player.last_error,
            'last_error': self._last_error,
            'clip_count': len(clips),
            'current_clip_exists': bool(self.current_clip_id and await self.clip_store.get_clip(self.current_clip_id)),
            'selected_output': selected_output.to_dict() if selected_output else None,
            'connected_controllers': len(self.state.connected_controllers),
            'remote_enabled': self.state.remote_enabled,
            'preview_enabled': self.state.preview_enabled,
            'safe_mode_enabled': self.state.safe_mode_enabled,
            'live_controls_armed': self.state.live_controls_armed(),
            'clips_last_synced_at': self._last_clip_sync_at,
            'storage_free_bytes': free_bytes,
            'storage_total_bytes': total_bytes,
        }

    async def snapshot(self) -> Dict[str, Any]:
        clips = await self.clip_store.list_clips()
        return {
            'transport': self.state.transport.to_dict(),
            'clips': [clip.to_dict() for clip in clips],
            'preview_enabled': self.state.preview_enabled,
            'remote_enabled': self.state.remote_enabled,
            'connections': self.state.connection_snapshot(),
            'logs': self.state.logs_snapshot(),
            'audio': self.audio_snapshot(),
            'outputs': await self.list_outputs(),
            'playlist': await self.playlist_snapshot(),
            'network': await self.network_info.snapshot(),
            'health': await self.health_snapshot(),
            'safety': self.state.safety_snapshot(),
            'app_name': self.config.app_name,
        }

    async def _playlist_position_for_clip(self, clip_id: int) -> int:
        playlist = await self.playlist_store.get_active_playlist()
        for item in playlist.get('items', []):
            if item['clip_id'] == clip_id:
                return item['position']
        return 0

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(self.config.ws_tick_seconds)
            if self.state.transport.status != 'play' or not self.current_clip_id or self._play_started_at is None:
                continue
            if not await self.player.is_available():
                recovered = await self._recover_player_for_current_clip()
                if not recovered:
                    await self.stop_playback()
                    continue
            clip = await self.clip_store.get_clip(self.current_clip_id)
            if not clip:
                await self._report_error('playback', f'Current clip {self.current_clip_id} no longer exists.')
                await self.stop_playback()
                continue
            if self._pause_started_at is not None:
                elapsed = max(0.0, (self._pause_started_at - self._play_started_at) - self._accumulated_pause_seconds)
            else:
                elapsed = max(0.0, (time.monotonic() - self._play_started_at) - self._accumulated_pause_seconds)
            if not self.state.transport.loop and elapsed >= clip.duration_seconds and clip.duration_seconds > 0:
                if self._playlist_mode:
                    await self.play_next_playlist_item()
                else:
                    await self.stop_playback()
                continue
            if self.state.transport.loop and clip.duration_seconds > 0:
                elapsed = elapsed % clip.duration_seconds
            remaining = max(0.0, clip.duration_seconds - elapsed)
            await self.state.set_transport(
                elapsed_seconds=elapsed,
                remaining_seconds=remaining,
                total_seconds=clip.duration_seconds,
                timecode=seconds_to_timecode(elapsed, clip.framerate),
                display_timecode=seconds_to_timecode(elapsed, clip.framerate),
            )

    async def _health_reporter(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            await self._publish_health()
            await self.state.publish('safety', self.state.safety_snapshot())

    async def _publish_health(self) -> None:
        await self.state.publish('health', await self.health_snapshot())

    async def _start_clip_playback(self, clip, use_loop: bool) -> bool:
        if not await self._ensure_player_ready():
            await self._report_error('player', f'Player unavailable: {self.player.last_error or "startup failed"}')
            await self._publish_health()
            return False
        started = await self.player.play_file(clip.filepath, loop=use_loop, is_vertical=clip.is_vertical)
        if started:
            return True
        await self._report_error('player', f'Playback failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
        if not await self._ensure_player_ready(force_restart=True):
            await self._publish_health()
            return False
        started = await self.player.play_file(clip.filepath, loop=use_loop, is_vertical=clip.is_vertical)
        if not started:
            await self._report_error('player', f'Playback recovery failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
            await self.player.stop_process()
            await self._publish_health()
            return False
        return True

    async def _ensure_player_ready(self, force_restart: bool = False) -> bool:
        if force_restart and self.player.process is not None:
            await self.player.stop_process()
        if await self.player.is_available():
            return True
        try:
            with contextlib.suppress(FileNotFoundError):
                await self.player.start()
            if not await self.player.is_available():
                return False
            await self.player.set_video_format(self.state.transport.video_format)
            if self._volume != 100:
                await self.player.set_volume(self._volume)
            if self._muted:
                await self.player.set_mute(True)
            return True
        except Exception as exc:
            await self._report_error('player', f'Player start failed: {exc}')
            return False

    async def _recover_player_for_current_clip(self) -> bool:
        if self._recovering_player:
            return False
        self._recovering_player = True
        try:
            clip = await self.clip_store.get_clip(self.current_clip_id or 0)
            if not clip:
                return False
            await self._report_error('player', 'Player connection lost. Attempting automatic recovery.')
            return await self._start_clip_playback(clip, self.state.transport.loop)
        finally:
            self._recovering_player = False

    async def _report_error(self, source: str, message: str) -> None:
        self._last_error = message
        error_key = f'{source}:{message}'
        if self._last_error_key == error_key:
            return
        self._last_error_key = error_key
        await self.state.add_log('error', source, message)
