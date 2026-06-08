from __future__ import annotations

import asyncio
import contextlib
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
        self._volume: int = 100
        self._muted: bool = False
        self._playlist_mode = False
        self._playlist_loop = False

    async def start(self) -> None:
        self._ticker_task = asyncio.create_task(self._ticker())

    async def stop(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker_task

    async def list_clips(self):
        return await self.clip_store.list_clips()

    async def refresh_clips(self) -> None:
        await self.clip_store.sync_with_disk()
        await self.playlist_store.sync_active_playlist_from_clips()
        clips = await self.clip_store.list_clips()
        await self.state.publish('clips', {'clips': [clip.to_dict() for clip in clips]})
        await self.state.publish('playlist', await self.playlist_store.get_active_playlist())

    async def goto_clip(self, clip_id: int) -> bool:
        clip = await self.clip_store.get_clip(clip_id)
        if not clip:
            return False
        self.current_clip_id = clip.deck_id
        await self.state.set_transport(
            clip_id=clip.deck_id,
            timecode='00:00:00:00',
            display_timecode='00:00:00:00',
            total_seconds=clip.duration_seconds,
            remaining_seconds=clip.duration_seconds,
            elapsed_seconds=0.0,
            video_format=self.config.default_video_format,
            loop=clip.loop_enabled,
        )
        return True

    async def play(self, clip_id: int | None = None, loop: bool | None = None, single_clip: bool | None = None) -> bool:
        target_clip_id = clip_id or self.current_clip_id or 1
        clip = await self.clip_store.get_clip(target_clip_id)
        if not clip:
            return False
        self.current_clip_id = clip.deck_id
        use_loop = clip.loop_enabled if loop is None else loop
        await self.player.play_file(clip.filepath, loop=use_loop, is_vertical=clip.is_vertical)
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
            video_format=self.config.default_video_format,
            playlist_mode=self._playlist_mode,
            playlist_loop=self._playlist_loop,
            playlist_position=await self._playlist_position_for_clip(clip.deck_id),
        )
        return True

    async def pause(self) -> None:
        await self.player.pause(True)
        if self._pause_started_at is None:
            self._pause_started_at = time.monotonic()
        await self.state.set_transport(status='stopped', paused=True, speed=0)

    async def resume(self) -> None:
        await self.player.pause(False)
        if self._pause_started_at is not None:
            self._accumulated_pause_seconds += time.monotonic() - self._pause_started_at
            self._pause_started_at = None
        await self.state.set_transport(status='play', paused=False, speed=100)

    async def stop_playback(self) -> None:
        await self.player.stop()
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

    async def play_playlist(self, loop: bool = False) -> bool:
        playlist = await self.playlist_store.get_active_playlist()
        items = playlist.get('items', [])
        if not items:
            return False
        self._playlist_mode = True
        self._playlist_loop = loop
        return await self.play(clip_id=items[0]['clip_id'], loop=False, single_clip=False)

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

    async def list_outputs(self) -> list[dict[str, Any]]:
        outputs = await self.output_manager.list_outputs()
        return [item.to_dict() for item in outputs]

    async def select_output(self, output_id: str) -> None:
        await self.output_manager.set_selected_output(output_id)
        await self.player.set_output(output_id)
        await self.state.publish('outputs', {'outputs': await self.list_outputs()})

    async def playlist_snapshot(self) -> Dict[str, Any]:
        return await self.playlist_store.get_active_playlist()

    async def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(volume, 100))
        await self.player.set_volume(self._volume)
        await self.state.publish('audio', {'volume': self._volume, 'muted': self._muted})

    async def set_mute(self, enabled: bool) -> None:
        self._muted = enabled
        await self.player.set_mute(enabled)
        await self.state.publish('audio', {'volume': self._volume, 'muted': self._muted})

    def audio_snapshot(self) -> Dict[str, Any]:
        return {'volume': self._volume, 'muted': self._muted}

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
            clip = await self.clip_store.get_clip(self.current_clip_id)
            if not clip:
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
