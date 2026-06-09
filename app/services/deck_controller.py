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
from app.services.standby_slate import StandbySlateService

# Forward-only speed window. Reverse playback is intentionally unsupported: mpv
# backward decode needs a large demuxer back-cache, which a Pi-class SBC cannot
# sustain at 1080p. Above 2x the Pi 3B+ decoder starts dropping frames.
PLAYBACK_SPEED_MIN_PERCENT = 10
PLAYBACK_SPEED_MAX_PERCENT = 200


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
        slate: StandbySlateService | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.clip_store = clip_store
        self.playlist_store = playlist_store
        self.output_manager = output_manager
        self.network_info = network_info
        self.player = player
        self.slate = slate
        self.current_clip_id: int | None = None
        self._play_started_at: float | None = None
        self._pause_started_at: float | None = None
        self._accumulated_pause_seconds: float = 0.0
        self._speed: float = 1.0
        self._ticker_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._volume: int = 100
        self._muted: bool = False
        self._output_canvas_mode: str = 'auto'
        self._playlist_mode = False
        self._playlist_loop = False
        self._last_clip_sync_at: float | None = None
        self._last_error: str | None = None
        self._last_error_key: str | None = None
        self._recovering_player = False
        self._media_publish_task: asyncio.Task | None = None
        self._last_health_payload: Dict[str, Any] | None = None
        self._last_safety_payload: Dict[str, Any] | None = None

    async def start(self) -> None:
        self._ticker_task = asyncio.create_task(self._ticker())
        self._health_task = asyncio.create_task(self._health_reporter())
        asyncio.create_task(self._enter_standby(ensure_player=True))

    async def _enter_standby(self, ensure_player: bool = False, force: bool = False) -> None:
        if not self.slate:
            return
        # On the startup task, bail out if a clip became active in the meantime.
        if not force and (self.current_clip_id is not None or self.state.transport.status == 'play'):
            return
        try:
            slate_path = await self.slate.ensure_slate()
            if not slate_path:
                return
            if ensure_player and not await self._ensure_player_ready():
                return
            if not await self.player.is_available():
                return
            await self.player.show_standby(slate_path)
        except Exception:
            # The standby slate is cosmetic; never let it disrupt playback.
            pass

    async def stop(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker_task
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
        if self._media_publish_task:
            self._media_publish_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._media_publish_task

    async def list_clips(self):
        return await self.clip_store.list_clips()

    async def refresh_clips(self) -> None:
        await self.clip_store.sync_with_disk()
        await self.playlist_store.sync_active_playlist_from_clips()
        await self._publish_media_state()

    async def schedule_media_refresh_publish(self) -> None:
        if self._media_publish_task and not self._media_publish_task.done():
            return
        self._media_publish_task = asyncio.create_task(self._debounced_media_publish())

    async def _debounced_media_publish(self) -> None:
        try:
            await asyncio.sleep(0.25)
            await self.playlist_store.sync_active_playlist_from_clips()
            await self._publish_media_state()
        finally:
            self._media_publish_task = None

    async def _publish_media_state(self) -> None:
        clips = await self.clip_store.list_clips()
        folders = await self.clip_store.list_folders()
        playlists = await self.playlist_store.list_playlists()
        self._last_clip_sync_at = time.time()
        await self.state.publish('clips', {'clips': [clip.to_dict() for clip in clips]})
        await self.state.publish('folders', {'folders': folders})
        await self.state.publish('playlists', {'playlists': playlists})
        await self.state.publish('playlist', await self.playlist_store.get_active_playlist())
        await self.state.publish('slot', await self.slot_snapshot())
        await self._publish_health()

    def _speed_percent(self) -> int:
        return int(round(self._speed * 100))

    def _clamp_speed_percent(self, percent: float) -> int:
        return int(round(max(float(PLAYBACK_SPEED_MIN_PERCENT), min(float(percent), float(PLAYBACK_SPEED_MAX_PERCENT)))))

    def _clock_elapsed(self, now: float | None = None) -> float:
        """Media-time position derived from the wall clock, scaled by playback speed."""
        if self._play_started_at is None:
            return max(0.0, float(self.state.transport.elapsed_seconds or 0.0))
        anchor = self._pause_started_at if self._pause_started_at is not None else (now if now is not None else time.monotonic())
        return max(0.0, (anchor - self._play_started_at - self._accumulated_pause_seconds) * self._speed)

    def _anchor_clock(self, elapsed: float, now: float | None = None) -> None:
        """Reposition the wall clock so _clock_elapsed(now) equals ``elapsed``."""
        anchor = self._pause_started_at if self._pause_started_at is not None else (now if now is not None else time.monotonic())
        self._play_started_at = anchor - self._accumulated_pause_seconds - (elapsed / self._speed)

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
        in_point, out_point = clip.trim_bounds()
        if not await self.player.cue_file(clip.filepath, loop=clip.loop_enabled, is_vertical=clip.is_vertical, start=in_point):
            await self._report_error('player', f'Cue failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
            await self._publish_health()
            return False
        self.current_clip_id = clip.deck_id
        now = time.monotonic()
        self._speed = 1.0
        self._pause_started_at = now
        self._accumulated_pause_seconds = 0.0
        self._anchor_clock(in_point, now)
        cue_timecode = seconds_to_timecode(in_point, clip.framerate)
        await self.state.set_transport(
            status='stopped',
            speed=0,
            playback_speed_percent=100,
            clip_id=clip.deck_id,
            timecode=cue_timecode,
            display_timecode=cue_timecode,
            total_seconds=clip.duration_seconds,
            remaining_seconds=max(0.0, out_point - in_point),
            elapsed_seconds=in_point,
            video_format=self.state.transport.video_format,
            loop=clip.loop_enabled,
            paused=True,
            **self._mark_transport_fields(clip),
        )
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def play(
        self,
        clip_id: int | None = None,
        loop: bool | None = None,
        single_clip: bool | None = None,
        speed: float | None = None,
    ) -> bool:
        if speed is not None and float(speed) <= 0:
            await self._report_error('playback', 'Reverse or zero-speed playback is not supported.')
            await self._publish_health()
            return False
        speed_percent = 100 if speed is None else self._clamp_speed_percent(speed)
        target_clip_id = clip_id or self.current_clip_id
        if not target_clip_id:
            await self._report_error('playback', 'Cannot play: no clip is currently loaded.')
            await self._publish_health()
            return False
        clip = await self.clip_store.get_clip(target_clip_id)
        if not clip:
            await self._report_error('playback', f'Cannot play clip {target_clip_id}: clip not found.')
            await self._publish_health()
            return False
        if not clip.filepath:
            await self._report_error('playback', f'Cannot play clip "{clip.name}": missing file path.')
            await self._publish_health()
            return False
        use_loop = clip.loop_enabled if loop is None else loop
        was_cued_clip = self.current_clip_id == clip.deck_id and self.state.transport.clip_id == clip.deck_id
        self.current_clip_id = clip.deck_id
        if (
            was_cued_clip
            and self.state.transport.paused
            and await self.player.is_available()
        ):
            resumed_at = time.monotonic()
            elapsed_at_resume = self._clock_elapsed(resumed_at)
            if not await self.player.set_loop(use_loop):
                await self._report_error('player', f'Loop update failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
                await self._publish_health()
                return False
            speed_percent = await self._apply_player_speed(speed_percent, fallback_percent=self._speed_percent())
            if not await self.player.pause(False):
                await self._report_error('player', f'Resume failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
                await self._publish_health()
                return False
            if self._pause_started_at is not None:
                self._accumulated_pause_seconds += resumed_at - self._pause_started_at
                self._pause_started_at = None
            self._speed = speed_percent / 100
            self._anchor_clock(elapsed_at_resume, resumed_at)
            await self.state.set_transport(
                status='play',
                speed=speed_percent,
                playback_speed_percent=speed_percent,
                clip_id=clip.deck_id,
                loop=use_loop,
                single_clip=bool(single_clip),
                paused=False,
                total_seconds=clip.duration_seconds,
                remaining_seconds=self.state.transport.remaining_seconds or clip.duration_seconds,
                elapsed_seconds=self.state.transport.elapsed_seconds,
                video_format=self.state.transport.video_format,
                playlist_mode=self._playlist_mode,
                playlist_loop=self._playlist_loop,
                playlist_position=await self._playlist_position_for_clip(clip.deck_id),
            )
            self._last_error = None
            self._last_error_key = None
            await self._publish_health()
            return True
        in_point, out_point = clip.trim_bounds()
        started = await self._start_clip_playback(clip, use_loop, start_seconds=in_point)
        if not started:
            return False
        if speed_percent != 100:
            speed_percent = await self._apply_player_speed(speed_percent, fallback_percent=100)
        self._speed = speed_percent / 100
        self._pause_started_at = None
        self._accumulated_pause_seconds = 0.0
        self._anchor_clock(in_point, time.monotonic())
        await self.state.set_transport(
            status='play',
            speed=speed_percent,
            playback_speed_percent=speed_percent,
            clip_id=clip.deck_id,
            loop=use_loop,
            single_clip=bool(single_clip),
            paused=False,
            total_seconds=clip.duration_seconds,
            remaining_seconds=max(0.0, out_point - in_point),
            elapsed_seconds=in_point,
            timecode=seconds_to_timecode(in_point, clip.framerate),
            display_timecode=seconds_to_timecode(in_point, clip.framerate),
            video_format=self.state.transport.video_format,
            playlist_mode=self._playlist_mode,
            playlist_loop=self._playlist_loop,
            playlist_position=await self._playlist_position_for_clip(clip.deck_id),
            **self._mark_transport_fields(clip),
        )
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def _apply_player_speed(self, percent: int, fallback_percent: int) -> int:
        """Push a playback speed to mpv. A failed speed change must never kill a
        running take, so on error report it and return the speed still in effect."""
        if await self.player.set_speed(percent / 100):
            return percent
        await self._report_error('player', f'Speed update failed: {self.player.last_error or "unknown player error"}')
        return fallback_percent

    async def set_playback_speed(self, percent: float) -> bool:
        if percent is None or float(percent) <= 0:
            await self._report_error('playback', 'Reverse or zero-speed playback is not supported.')
            await self._publish_health()
            return False
        clip_id = self.current_clip_id or self.state.transport.clip_id
        if not clip_id:
            await self._report_error('playback', 'Cannot change speed: no clip is currently loaded.')
            await self._publish_health()
            return False
        speed_percent = self._clamp_speed_percent(percent)
        if not await self.player.is_available() or not await self.player.set_speed(speed_percent / 100):
            await self._report_error('player', f'Speed update failed: {self.player.last_error or "player unavailable"}')
            await self._publish_health()
            return False
        now = time.monotonic()
        elapsed = self._clock_elapsed(now)
        self._speed = speed_percent / 100
        if self._play_started_at is not None:
            self._anchor_clock(elapsed, now)
        is_running = self.state.transport.status == 'play' and not self.state.transport.paused
        await self.state.set_transport(
            speed=speed_percent if is_running else 0,
            playback_speed_percent=speed_percent,
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
        await self.state.set_transport(status='play', paused=False, speed=self._speed_percent())

    async def seek_current_clip(self, seconds: float) -> bool:
        clip_id = self.current_clip_id or self.state.transport.clip_id
        if not clip_id:
            await self._report_error('playback', 'Cannot seek: no clip is currently loaded.')
            await self._publish_health()
            return False
        clip = await self.clip_store.get_clip(clip_id)
        if not clip:
            await self._report_error('playback', f'Cannot seek clip {clip_id}: clip not found.')
            await self._publish_health()
            return False
        if clip.media_kind != 'video':
            await self._report_error('playback', f'Cannot seek "{clip.name}": timeline scrubbing is only available for video clips.')
            await self._publish_health()
            return False
        if not await self.player.is_available():
            await self._report_error('player', f'Seek failed for "{clip.name}": {self.player.last_error or "player unavailable"}')
            await self._publish_health()
            return False
        target = max(0.0, min(float(seconds), float(clip.duration_seconds or 0.0)))
        if not await self.player.seek_absolute(target):
            await self._report_error('player', f'Seek failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
            await self._publish_health()
            return False
        self.current_clip_id = clip.deck_id
        now = time.monotonic()
        if self.state.transport.paused:
            self._pause_started_at = self._pause_started_at or now
        else:
            self._pause_started_at = None
        self._anchor_clock(target, now)
        await self._set_transport_position(clip, target)
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def set_clip_marks(
        self,
        deck_id: int,
        mark_in: float | None = None,
        mark_out: float | None = None,
    ) -> bool:
        clip = await self.clip_store.get_clip(deck_id)
        if not clip:
            await self._report_error('playback', f'Cannot set marks for clip {deck_id}: clip not found.')
            await self._publish_health()
            return False
        if clip.media_kind != 'video':
            await self._report_error('playback', f'Cannot set marks for "{clip.name}": marks are only available for video clips.')
            await self._publish_health()
            return False
        duration = max(0.0, float(clip.duration_seconds or 0.0))
        resolved_in = clip.mark_in_seconds if mark_in is None else max(0.0, min(float(mark_in), duration))
        resolved_out = clip.mark_out_seconds if mark_out is None else max(0.0, min(float(mark_out), duration))
        if resolved_out > 0 and resolved_in >= resolved_out:
            await self._report_error('playback', f'Cannot set marks for "{clip.name}": the in point must come before the out point.')
            await self._publish_health()
            return False
        await self.clip_store.set_marks(
            deck_id,
            None if mark_in is None else resolved_in,
            None if mark_out is None else resolved_out,
        )
        await self.refresh_clips()
        if self.current_clip_id == deck_id:
            updated = await self.clip_store.get_clip(deck_id)
            if updated:
                await self._set_transport_position(updated, float(self.state.transport.elapsed_seconds or 0.0))
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def stop_playback(self) -> None:
        if await self.player.is_available():
            if not await self.player.stop():
                await self._report_error('player', f'Stop failed: {self.player.last_error or "unknown player error"}')
        self._play_started_at = None
        self._pause_started_at = None
        self._accumulated_pause_seconds = 0.0
        self._speed = 1.0
        self._playlist_mode = False
        await self.state.set_transport(
            status='stopped',
            speed=0,
            playback_speed_percent=100,
            paused=False,
            elapsed_seconds=0.0,
            remaining_seconds=self.state.transport.total_seconds,
            timecode='00:00:00:00',
            display_timecode='00:00:00:00',
            playlist_mode=False,
        )
        await self._enter_standby(force=True)
        await self._publish_health()

    async def protocol_clips_add(self, clip_id: int | None = None, name: str | None = None) -> bool:
        clip = None
        if clip_id:
            clip = await self.clip_store.get_clip(clip_id)
        elif name:
            target = name.strip().lower()
            clips = await self.clip_store.list_clips()
            clip = next((c for c in clips if c.name.lower() == target or c.filename.lower() == target), None)
        if not clip:
            return False
        playlist = await self.playlist_store.get_active_playlist()
        summary = playlist.get('playlist')
        if not summary:
            return False
        await self.playlist_store.add_clip_to_playlist(summary['id'], clip.deck_id)
        await self.state.add_log('info', 'hyperdeck', f'Timeline add: "{clip.name}" appended to "{summary["name"]}".')
        await self._publish_media_state()
        return True

    async def protocol_clips_clear(self) -> bool:
        playlist = await self.playlist_store.get_active_playlist()
        summary = playlist.get('playlist')
        if not summary:
            return False
        await self.playlist_store.clear_playlist(summary['id'])
        await self.state.add_log('info', 'hyperdeck', f'Timeline cleared: "{summary["name"]}".')
        await self._publish_media_state()
        return True

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

    async def set_tags(self, deck_id: int, tags: str) -> bool:
        clip = await self.clip_store.get_clip(deck_id)
        if not clip:
            return False
        await self.clip_store.set_tags(deck_id, tags)
        await self.refresh_clips()
        return True

    async def set_still_duration(self, deck_id: int, seconds: float) -> bool:
        clip = await self.clip_store.get_clip(deck_id)
        if not clip:
            await self._report_error('playback', f'Cannot set duration for clip {deck_id}: clip not found.')
            await self._publish_health()
            return False
        if clip.media_kind != 'image':
            await self._report_error('playback', f'Cannot set duration for "{clip.name}": only stills have a configurable duration.')
            await self._publish_health()
            return False
        if float(seconds or 0) <= 0:
            await self._report_error('playback', f'Cannot set duration for "{clip.name}": duration must be positive.')
            await self._publish_health()
            return False
        await self.clip_store.set_duration(deck_id, float(seconds))
        await self.refresh_clips()
        if self.current_clip_id == deck_id:
            updated = await self.clip_store.get_clip(deck_id)
            if updated:
                await self._set_transport_position(updated, float(self.state.transport.elapsed_seconds or 0.0))
        self._last_error = None
        self._last_error_key = None
        await self._publish_health()
        return True

    async def set_loop(self, deck_id: int, enabled: bool) -> None:
        updated = await self.clip_store.set_loop(deck_id, enabled)
        if updated and self.current_clip_id == deck_id:
            if await self.player.is_available() and not await self.player.set_loop(enabled):
                await self._report_error('player', f'Loop update failed: {self.player.last_error or "unknown player error"}')
            await self.state.set_transport(loop=enabled)
            await self._publish_health()
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
        if enabled:
            return
        if self.state.transport.status != 'play' or self.state.transport.paused:
            return
        await self.state.add_log(
            'info',
            'hyperdeck',
            'Preview disabled by controller; pausing playback on the current frame.',
        )
        await self.pause()

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
        clip = await self.clip_store.get_clip(clip_id)
        if not clip:
            return False
        return await self.play(clip_id=clip_id, loop=clip.loop_enabled, single_clip=True)

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
        loop_item = (next_item.get('end_behavior') or 'next') == 'loop'
        return await self.play(clip_id=next_item['clip_id'], loop=loop_item, single_clip=False)

    async def play_playlist_from_position(self, position: int, loop: bool | None = None) -> bool:
        playlist = await self.playlist_store.get_active_playlist()
        items = playlist.get('items', [])
        if not items:
            return False
        index = max(1, min(position, len(items))) - 1
        self._playlist_mode = True
        if loop is not None:
            self._playlist_loop = loop
        loop_item = (items[index].get('end_behavior') or 'next') == 'loop'
        return await self.play(clip_id=items[index]['clip_id'], loop=loop_item, single_clip=False)

    async def list_outputs(self) -> list[dict[str, Any]]:
        outputs = await self.output_manager.list_outputs()
        return [item.to_dict() for item in outputs]

    async def select_output(self, output_id: str) -> None:
        await self.output_manager.set_selected_output(output_id)
        selected_output = await self.output_manager.get_selected_output()
        await self._apply_output_geometry(selected_output)
        await self.player.set_output(output_id)
        await self.state.publish('outputs', {'outputs': await self.list_outputs()})
        await self.state.publish('display', await self.display_snapshot())
        await self._publish_health()

    async def set_output_canvas_mode(self, mode: str) -> None:
        self._output_canvas_mode = mode or 'auto'
        selected_output = await self.output_manager.get_selected_output()
        await self._apply_output_geometry(selected_output)
        await self.state.publish('display', await self.display_snapshot())
        await self._publish_health()

    async def display_snapshot(self) -> Dict[str, Any]:
        selected_output = await self.output_manager.get_selected_output()
        modes = self._available_canvas_modes(selected_output)
        effective_width, effective_height = self._canvas_dimensions(selected_output)
        return {
            'canvas_mode': self._output_canvas_mode,
            'available_canvas_modes': modes,
            'selected_output_id': selected_output.id if selected_output else None,
            'selected_output_label': selected_output.label if selected_output else None,
            'detected_output_mode': selected_output.current_mode if selected_output else None,
            'effective_width': effective_width,
            'effective_height': effective_height,
        }

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
        media_processing = await self._media_processing_snapshot()
        outputs = await self.output_manager.list_outputs()
        selected_output = next((item for item in outputs if item.selected), None)
        effective_width, effective_height = self._canvas_dimensions(selected_output)
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
            'output_canvas_mode': self._output_canvas_mode,
            'effective_output_width': effective_width,
            'effective_output_height': effective_height,
            'connected_controllers': len(self.state.connected_controllers),
            'remote_enabled': self.state.remote_enabled,
            'preview_enabled': self.state.preview_enabled,
            'safe_mode_enabled': self.state.safe_mode_enabled,
            'live_controls_armed': self.state.live_controls_armed(),
            'clips_last_synced_at': self._last_clip_sync_at,
            'media_processing': media_processing,
            'storage_free_bytes': free_bytes,
            'storage_total_bytes': total_bytes,
        }

    async def export_snapshot(self) -> Dict[str, Any]:
        clips = await self.clip_store.list_clips()
        filenames = {clip.deck_id: clip.filename for clip in clips}
        return {
            'format': 'deckpilot-export',
            'version': 1,
            'app_name': self.config.app_name,
            'clips': await self.clip_store.export_entries(),
            'folders': await self.clip_store.list_folders(),
            'playlists': await self.playlist_store.export_playlists(filenames),
        }

    async def import_snapshot(self, payload: Dict[str, Any]) -> Dict[str, int]:
        if not isinstance(payload, dict) or payload.get('format') != 'deckpilot-export':
            raise ValueError('Not a DeckPilot export file.')
        for folder in payload.get('folders') or []:
            if isinstance(folder, str) and folder.strip():
                await self.clip_store.create_folder(folder)
        clips_applied = await self.clip_store.apply_import_entries(payload.get('clips') or [])
        clips = await self.clip_store.list_clips()
        ids_by_filename = {clip.filename: clip.deck_id for clip in clips}
        playlists_applied = await self.playlist_store.apply_import(payload.get('playlists') or [], ids_by_filename)
        await self.refresh_clips()
        return {'clips': clips_applied, 'playlists': playlists_applied}

    async def snapshot(self) -> Dict[str, Any]:
        clips = await self.clip_store.list_clips()
        return {
            'transport': self.state.transport.to_dict(),
            'clips': [clip.to_dict() for clip in clips],
            'media_processing': await self._media_processing_snapshot(),
            'folders': await self.clip_store.list_folders(),
            'playlists': await self.playlist_store.list_playlists(),
            'preview_enabled': self.state.preview_enabled,
            'remote_enabled': self.state.remote_enabled,
            'connections': self.state.connection_snapshot(),
            'logs': self.state.logs_snapshot(),
            'audio': self.audio_snapshot(),
            'outputs': await self.list_outputs(),
            'display': await self.display_snapshot(),
            'playlist': await self.playlist_snapshot(),
            'network': await self.network_info.snapshot(),
            'health': await self.health_snapshot(),
            'safety': self.state.safety_snapshot(),
            'app_name': self.config.app_name,
        }

    async def _current_playlist_end_behavior(self) -> str:
        playlist = await self.playlist_store.get_active_playlist()
        items = playlist.get('items', [])
        current_id = self.current_clip_id or self.state.transport.clip_id
        item = next((entry for entry in items if entry['clip_id'] == current_id), None)
        return (item or {}).get('end_behavior') or 'next'

    async def _hold_at_position(self, clip, position_seconds: float) -> None:
        """End-of-item HOLD: freeze on the out frame and wait for the operator."""
        if not await self.player.pause(True):
            await self.stop_playback()
            return
        now = time.monotonic()
        self._pause_started_at = now
        self._anchor_clock(position_seconds, now)
        await self._set_transport_position(clip, position_seconds)
        await self.state.set_transport(status='stopped', paused=True, speed=0)

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
            elapsed = self._clock_elapsed()
            in_point, out_point = clip.trim_bounds()
            if not self.state.transport.loop and out_point > 0 and elapsed >= out_point:
                if self._playlist_mode:
                    behavior = await self._current_playlist_end_behavior()
                    if behavior == 'stop':
                        await self.stop_playback()
                    elif behavior == 'hold':
                        await self._hold_at_position(clip, out_point)
                    else:
                        await self.play_next_playlist_item()
                else:
                    await self.stop_playback()
                continue
            window = out_point - in_point
            if self.state.transport.loop and window > 0:
                elapsed = in_point + ((elapsed - in_point) % window)
            await self._set_transport_position(clip, elapsed)

    async def _health_reporter(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            await self._publish_health()
            safety = self.state.safety_snapshot()
            if safety != self._last_safety_payload:
                self._last_safety_payload = safety
                await self.state.publish('safety', safety)

    async def _publish_health(self) -> None:
        # Idle decks should be silent: only broadcast health when it changed.
        payload = await self.health_snapshot()
        if payload == self._last_health_payload:
            return
        self._last_health_payload = payload
        await self.state.publish('health', payload)

    async def _media_processing_snapshot(self) -> Dict[str, int]:
        processing_method = getattr(self.clip_store, 'processing_status', None)
        if not callable(processing_method):
            return {'pending': 0, 'processing': 0, 'error': 0, 'ready': 0, 'queued': 0}
        return await processing_method()

    async def _set_transport_position(self, clip, elapsed: float) -> None:
        elapsed = max(0.0, min(float(elapsed), float(clip.duration_seconds or 0.0)))
        _in_point, out_point = clip.trim_bounds()
        remaining = max(0.0, out_point - elapsed)
        timecode = seconds_to_timecode(elapsed, clip.framerate)
        await self.state.set_transport(
            elapsed_seconds=elapsed,
            remaining_seconds=remaining,
            total_seconds=clip.duration_seconds,
            timecode=timecode,
            display_timecode=timecode,
            **self._mark_transport_fields(clip),
        )

    def _mark_transport_fields(self, clip) -> Dict[str, Any]:
        in_point, out_point = clip.trim_bounds()
        duration = max(0.0, float(clip.duration_seconds or 0.0))
        return {
            'mark_in_seconds': in_point if in_point > 0 else 0.0,
            'mark_out_seconds': out_point if out_point < duration else 0.0,
            'trim_active': clip.has_marks(),
        }

    async def _apply_output_geometry(self, selected_output) -> None:
        width, height = self._canvas_dimensions(selected_output)
        await self.player.set_output_geometry(width, height)

    def _canvas_dimensions(self, selected_output) -> tuple[int | None, int | None]:
        if self._output_canvas_mode != 'auto':
            return _parse_canvas_mode(self._output_canvas_mode)
        if selected_output:
            return selected_output.width, selected_output.height
        return None, None

    def _available_canvas_modes(self, selected_output) -> list[str]:
        values: list[str] = ['auto']
        if selected_output:
            for mode in selected_output.modes:
                if mode not in values:
                    values.append(mode)
            if selected_output.current_mode and selected_output.current_mode not in values:
                values.append(selected_output.current_mode)
        for common in ('1920x1080', '2560x1440', '1280x720'):
            if common not in values:
                values.append(common)
        return values

    async def _start_clip_playback(self, clip, use_loop: bool, start_seconds: float = 0.0) -> bool:
        if not await self._ensure_player_ready():
            await self._report_error('player', f'Player unavailable: {self.player.last_error or "startup failed"}')
            await self._publish_health()
            return False
        started = await self.player.play_file(clip.filepath, loop=use_loop, is_vertical=clip.is_vertical, start=start_seconds)
        if started:
            return True
        await self._report_error('player', f'Playback failed for "{clip.name}": {self.player.last_error or "unknown player error"}')
        if not await self._ensure_player_ready(force_restart=True):
            await self._publish_health()
            return False
        started = await self.player.play_file(clip.filepath, loop=use_loop, is_vertical=clip.is_vertical, start=start_seconds)
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
            resume_at = max(0.0, float(self.state.transport.elapsed_seconds or 0.0))
            started = await self._start_clip_playback(clip, self.state.transport.loop, start_seconds=resume_at)
            if started:
                if self._speed_percent() != 100:
                    applied = await self._apply_player_speed(self._speed_percent(), fallback_percent=100)
                    self._speed = applied / 100
                self._pause_started_at = None
                self._anchor_clock(resume_at)
            return started
        finally:
            self._recovering_player = False

    async def _report_error(self, source: str, message: str) -> None:
        self._last_error = message
        error_key = f'{source}:{message}'
        if self._last_error_key == error_key:
            return
        self._last_error_key = error_key
        await self.state.add_log('error', source, message)


def _parse_canvas_mode(mode: str) -> tuple[int | None, int | None]:
    try:
        width_text, height_text = mode.lower().split('x', 1)
        width = int(width_text)
        height = int(height_text)
    except (ValueError, AttributeError):
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height
