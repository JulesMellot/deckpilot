from __future__ import annotations

import unittest
from dataclasses import dataclass

from app.core.config import AppConfig
from app.core.state import AppState
from app.services.deck_controller import DeckController


@dataclass
class FakeClip:
    deck_id: int
    name: str
    filepath: str
    duration_seconds: float = 12.0
    framerate: float = 25.0
    media_kind: str = 'video'
    is_vertical: bool = False
    loop_enabled: bool = False
    mark_in_seconds: float = 0.0
    mark_out_seconds: float = 0.0

    @property
    def filename(self) -> str:
        return self.filepath.split('/')[-1]

    def trim_bounds(self) -> tuple[float, float]:
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

    def to_dict(self) -> dict:
        return {
            'deck_id': self.deck_id,
            'name': self.name,
            'filename': self.filepath.split('/')[-1],
            'filepath': self.filepath,
            'duration_seconds': self.duration_seconds,
            'duration_timecode': '00:00:12:00',
            'framerate': self.framerate,
            'codec': 'h264',
            'width': 1920,
            'height': 1080,
            'media_kind': self.media_kind,
            'is_vertical': self.is_vertical,
            'thumbnail_path': None,
            'loop_enabled': self.loop_enabled,
            'folder': 'All',
        }


class FakeClipStore:
    def __init__(self, clips: list[FakeClip]) -> None:
        self.clips = {clip.deck_id: clip for clip in clips}

    async def get_clip(self, clip_id: int) -> FakeClip | None:
        return self.clips.get(clip_id)

    async def list_clips(self) -> list[FakeClip]:
        return list(self.clips.values())

    async def list_folders(self) -> list[str]:
        return ['All']

    async def sync_with_disk(self) -> None:
        return None

    async def set_loop(self, deck_id: int, enabled: bool) -> FakeClip | None:
        clip = self.clips.get(deck_id)
        if clip:
            clip.loop_enabled = enabled
        return clip

    async def set_marks(
        self,
        deck_id: int,
        mark_in_seconds: float | None,
        mark_out_seconds: float | None,
    ) -> FakeClip | None:
        clip = self.clips.get(deck_id)
        if clip:
            if mark_in_seconds is not None:
                clip.mark_in_seconds = mark_in_seconds
            if mark_out_seconds is not None:
                clip.mark_out_seconds = mark_out_seconds
        return clip


class FakePlaylistStore:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.added: list[int] = []
        self.cleared = 0

    async def sync_active_playlist_from_clips(self) -> None:
        return None

    async def list_playlists(self) -> list[dict]:
        return [{'id': 1, 'name': 'Main Playlist', 'is_active': True, 'item_count': len(self.items)}]

    async def get_active_playlist(self) -> dict:
        return {
            'playlist': {'id': 1, 'name': 'Main Playlist', 'is_active': True, 'item_count': len(self.items)},
            'items': list(self.items),
        }

    async def add_clip_to_playlist(self, playlist_id: int, clip_id: int) -> None:
        self.added.append(clip_id)
        self.items.append({
            'position': len(self.items) + 1,
            'clip_id': clip_id,
            'clip_name': f'Clip {clip_id}',
            'duration_timecode': '00:00:12:00',
            'loop_enabled': False,
            'auto_advance': False,
            'end_behavior': 'next',
        })

    async def clear_playlist(self, playlist_id: int) -> None:
        self.cleared += 1
        self.items = []

    async def reorder_active_playlist(self, deck_ids: list[int]) -> None:
        return None


class FakeOutput:
    def __init__(self) -> None:
        self.selected = True
        self.id = 'screen-1'
        self.label = 'Screen 1'
        self.current_mode = '1920x1080'
        self.width = 1920
        self.height = 1080
        self.modes = ['1920x1080']

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'label': self.label,
            'selected': self.selected,
            'current_mode': self.current_mode,
            'width': self.width,
            'height': self.height,
            'modes': list(self.modes),
        }


class FakeOutputManager:
    def __init__(self) -> None:
        self.output = FakeOutput()

    async def list_outputs(self) -> list[FakeOutput]:
        return [self.output]

    async def get_selected_output(self) -> FakeOutput:
        return self.output


class FakeNetworkInfo:
    async def snapshot(self) -> dict:
        return {'hyperdeck_target': '127.0.0.1:9993'}


class FakePlayer:
    def __init__(self) -> None:
        self.process = object()
        self.last_error: str | None = None
        self.available = True
        self.cue_calls: list[tuple[str, bool]] = []
        self.play_calls: list[tuple[str, bool]] = []
        self.cue_starts: list[float] = []
        self.play_starts: list[float] = []
        self.pause_calls: list[bool] = []
        self.loop_calls: list[bool] = []
        self.speed_calls: list[float] = []
        self.seek_calls: list[float] = []
        self.standby_calls: list[str] = []
        self.stop_calls = 0
        self.stop_process_calls = 0

    async def is_available(self) -> bool:
        return self.available

    async def show_standby(self, path: str) -> bool:
        self.standby_calls.append(path)
        return True

    async def cue_file(self, path: str, loop: bool = False, is_vertical: bool = False, start: float = 0.0) -> bool:
        self.cue_calls.append((path, loop))
        self.cue_starts.append(start)
        return True

    async def play_file(self, path: str, loop: bool = False, is_vertical: bool = False, start: float = 0.0) -> bool:
        self.play_calls.append((path, loop))
        self.play_starts.append(start)
        return True

    async def pause(self, enabled: bool = True) -> bool:
        self.pause_calls.append(enabled)
        return True

    async def set_loop(self, enabled: bool) -> bool:
        self.loop_calls.append(enabled)
        return True

    async def set_speed(self, factor: float) -> bool:
        self.speed_calls.append(factor)
        return True

    async def seek_absolute(self, seconds: float) -> bool:
        self.seek_calls.append(seconds)
        return True

    async def stop(self) -> bool:
        self.stop_calls += 1
        return True

    async def stop_process(self) -> None:
        self.stop_process_calls += 1

    async def set_video_format(self, video_format: str) -> None:
        return None

    async def set_volume(self, value: int) -> bool:
        return True

    async def set_mute(self, enabled: bool) -> bool:
        return True

    async def set_output_geometry(self, width: int | None, height: int | None) -> None:
        return None


class FakeSlate:
    def __init__(self, path: str | None = '/tmp/standby.png') -> None:
        self.path = path
        self.ensure_calls = 0

    async def ensure_slate(self) -> str | None:
        self.ensure_calls += 1
        return self.path


class DeckControllerCueLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clip = FakeClip(deck_id=7, name='Demo', filepath='/tmp/demo.mp4', loop_enabled=False)
        self.state = AppState(AppConfig())
        self.player = FakePlayer()
        self.clip_store = FakeClipStore([clip])
        self.controller = DeckController(
            config=AppConfig(),
            state=self.state,
            clip_store=self.clip_store,
            playlist_store=FakePlaylistStore(),
            output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(),
            player=self.player,
        )

    async def test_cue_then_play_resumes_loaded_clip_without_reload(self) -> None:
        ok = await self.controller.goto_clip(7)
        self.assertTrue(ok)

        ok = await self.controller.play(clip_id=7, loop=True, single_clip=True)

        self.assertTrue(ok)
        self.assertEqual(self.player.cue_calls, [('/tmp/demo.mp4', False)])
        self.assertEqual(self.player.play_calls, [])
        self.assertEqual(self.player.loop_calls, [True])
        self.assertEqual(self.player.pause_calls, [False])
        self.assertEqual(self.state.transport.status, 'play')
        self.assertFalse(self.state.transport.paused)
        self.assertTrue(self.state.transport.loop)

    async def test_set_loop_updates_active_player(self) -> None:
        await self.controller.goto_clip(7)

        await self.controller.set_loop(7, True)

        self.assertEqual(self.player.loop_calls, [True])
        self.assertTrue(self.state.transport.loop)
        self.assertTrue(self.clip_store.clips[7].loop_enabled)

    async def test_stop_playback_keeps_mpv_process_warm(self) -> None:
        await self.state.set_transport(status='play', paused=False, speed=100, clip_id=7)

        await self.controller.stop_playback()

        self.assertEqual(self.player.stop_calls, 1)
        self.assertEqual(self.player.stop_process_calls, 0)

    async def test_seek_current_clip_updates_cued_transport_position(self) -> None:
        await self.controller.goto_clip(7)

        ok = await self.controller.seek_current_clip(4.5)

        self.assertTrue(ok)
        self.assertEqual(self.player.seek_calls, [4.5])
        self.assertTrue(self.state.transport.paused)
        self.assertEqual(self.state.transport.status, 'stopped')
        self.assertAlmostEqual(self.state.transport.elapsed_seconds, 4.5, places=2)
        self.assertAlmostEqual(self.state.transport.remaining_seconds, 7.5, places=2)

    async def test_cue_clip_with_marks_starts_at_in_point(self) -> None:
        self.clip_store.clips[7].mark_in_seconds = 2.0
        self.clip_store.clips[7].mark_out_seconds = 8.0

        ok = await self.controller.goto_clip(7)

        self.assertTrue(ok)
        self.assertEqual(self.player.cue_starts, [2.0])
        self.assertAlmostEqual(self.state.transport.elapsed_seconds, 2.0, places=2)
        self.assertAlmostEqual(self.state.transport.remaining_seconds, 6.0, places=2)
        self.assertAlmostEqual(self.state.transport.total_seconds, 12.0, places=2)
        self.assertAlmostEqual(self.state.transport.mark_in_seconds, 2.0, places=2)
        self.assertAlmostEqual(self.state.transport.mark_out_seconds, 8.0, places=2)
        self.assertTrue(self.state.transport.trim_active)

    async def test_play_clip_with_marks_starts_at_in_point(self) -> None:
        self.clip_store.clips[7].mark_in_seconds = 3.0
        self.clip_store.clips[7].mark_out_seconds = 9.0

        ok = await self.controller.play(clip_id=7, single_clip=True)

        self.assertTrue(ok)
        self.assertEqual(self.player.play_starts, [3.0])
        self.assertAlmostEqual(self.state.transport.elapsed_seconds, 3.0, places=2)
        self.assertAlmostEqual(self.state.transport.remaining_seconds, 6.0, places=2)

    async def test_set_clip_marks_updates_cued_remaining(self) -> None:
        await self.controller.goto_clip(7)

        ok = await self.controller.set_clip_marks(7, mark_out=8.0)

        self.assertTrue(ok)
        self.assertAlmostEqual(self.clip_store.clips[7].mark_out_seconds, 8.0, places=2)
        self.assertAlmostEqual(self.state.transport.remaining_seconds, 8.0, places=2)
        self.assertAlmostEqual(self.state.transport.mark_out_seconds, 8.0, places=2)
        self.assertTrue(self.state.transport.trim_active)

    async def test_set_clip_marks_rejects_invalid_window(self) -> None:
        ok = await self.controller.set_clip_marks(7, mark_in=8.0, mark_out=2.0)

        self.assertFalse(ok)
        self.assertEqual(self.clip_store.clips[7].mark_in_seconds, 0.0)
        self.assertEqual(self.clip_store.clips[7].mark_out_seconds, 0.0)

    async def test_stop_playback_shows_standby_slate(self) -> None:
        slate = FakeSlate()
        controller = DeckController(
            config=AppConfig(),
            state=self.state,
            clip_store=self.clip_store,
            playlist_store=FakePlaylistStore(),
            output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(),
            player=self.player,
            slate=slate,
        )
        await self.state.set_transport(status='play', paused=False, speed=100, clip_id=7)

        await controller.stop_playback()

        self.assertEqual(self.player.standby_calls, ['/tmp/standby.png'])
        self.assertGreaterEqual(slate.ensure_calls, 1)

    async def test_stop_playback_without_slate_does_not_call_standby(self) -> None:
        await self.state.set_transport(status='play', paused=False, speed=100, clip_id=7)

        await self.controller.stop_playback()

        self.assertEqual(self.player.standby_calls, [])


class DeckControllerProtocolTimelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clips = [
            FakeClip(deck_id=1, name='Intro', filepath='/tmp/intro.mp4'),
            FakeClip(deck_id=2, name='Main', filepath='/tmp/main.mp4'),
        ]
        self.state = AppState(AppConfig())
        self.player = FakePlayer()
        self.playlist_store = FakePlaylistStore()
        self.controller = DeckController(
            config=AppConfig(),
            state=self.state,
            clip_store=FakeClipStore(clips),
            playlist_store=self.playlist_store,
            output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(),
            player=self.player,
        )

    async def test_protocol_clips_add_by_id(self) -> None:
        ok = await self.controller.protocol_clips_add(clip_id=2)

        self.assertTrue(ok)
        self.assertEqual(self.playlist_store.added, [2])

    async def test_protocol_clips_add_by_name_is_case_insensitive(self) -> None:
        ok = await self.controller.protocol_clips_add(name='intro')

        self.assertTrue(ok)
        self.assertEqual(self.playlist_store.added, [1])

    async def test_protocol_clips_add_unknown_clip_fails(self) -> None:
        ok = await self.controller.protocol_clips_add(name='ghost')

        self.assertFalse(ok)
        self.assertEqual(self.playlist_store.added, [])

    async def test_protocol_clips_clear_empties_timeline(self) -> None:
        await self.controller.protocol_clips_add(clip_id=1)

        ok = await self.controller.protocol_clips_clear()

        self.assertTrue(ok)
        self.assertEqual(self.playlist_store.cleared, 1)
        self.assertEqual(self.playlist_store.items, [])


class DeckControllerRundownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clips = [
            FakeClip(deck_id=1, name='Intro', filepath='/tmp/intro.mp4'),
            FakeClip(deck_id=2, name='Loop BG', filepath='/tmp/bg.mp4'),
        ]
        self.state = AppState(AppConfig())
        self.player = FakePlayer()
        self.playlist_store = FakePlaylistStore()
        self.clip_store = FakeClipStore(clips)
        self.controller = DeckController(
            config=AppConfig(),
            state=self.state,
            clip_store=self.clip_store,
            playlist_store=self.playlist_store,
            output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(),
            player=self.player,
        )
        await self.playlist_store.add_clip_to_playlist(1, 1)
        await self.playlist_store.add_clip_to_playlist(1, 2)

    async def test_play_from_position_honors_loop_end_behavior(self) -> None:
        self.playlist_store.items[1]['end_behavior'] = 'loop'

        ok = await self.controller.play_playlist_from_position(2)

        self.assertTrue(ok)
        self.assertTrue(self.state.transport.loop)

    async def test_current_playlist_end_behavior_reads_active_item(self) -> None:
        self.playlist_store.items[0]['end_behavior'] = 'hold'
        await self.controller.play_playlist_from_position(1)

        behavior = await self.controller._current_playlist_end_behavior()

        self.assertEqual(behavior, 'hold')

    async def test_hold_at_position_freezes_on_out_frame(self) -> None:
        await self.controller.play_playlist_from_position(1)
        clip = await self.clip_store.get_clip(1)

        await self.controller._hold_at_position(clip, 12.0)

        self.assertIn(True, self.player.pause_calls)
        self.assertEqual(self.state.transport.status, 'stopped')
        self.assertTrue(self.state.transport.paused)
        self.assertAlmostEqual(self.state.transport.elapsed_seconds, 12.0, places=2)
        self.assertTrue(self.state.transport.playlist_mode)
        self.assertAlmostEqual(self.controller._clock_elapsed(), 12.0, places=2)


class DeckControllerSpeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clip = FakeClip(deck_id=7, name='Demo', filepath='/tmp/demo.mp4', loop_enabled=False)
        self.state = AppState(AppConfig())
        self.player = FakePlayer()
        self.clip_store = FakeClipStore([clip])
        self.controller = DeckController(
            config=AppConfig(),
            state=self.state,
            clip_store=self.clip_store,
            playlist_store=FakePlaylistStore(),
            output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(),
            player=self.player,
        )

    async def test_play_with_speed_applies_player_speed_and_transport(self) -> None:
        ok = await self.controller.play(clip_id=7, single_clip=True, speed=50)

        self.assertTrue(ok)
        self.assertEqual(self.player.speed_calls, [0.5])
        self.assertEqual(self.state.transport.speed, 50)
        self.assertEqual(self.state.transport.playback_speed_percent, 50)

    async def test_play_rejects_reverse_speed(self) -> None:
        ok = await self.controller.play(clip_id=7, single_clip=True, speed=-100)

        self.assertFalse(ok)
        self.assertEqual(self.player.play_calls, [])

    async def test_set_playback_speed_clamps_into_supported_window(self) -> None:
        await self.controller.play(clip_id=7, single_clip=True)

        ok = await self.controller.set_playback_speed(1600)

        self.assertTrue(ok)
        self.assertEqual(self.player.speed_calls[-1], 2.0)
        self.assertEqual(self.state.transport.speed, 200)
        self.assertEqual(self.state.transport.playback_speed_percent, 200)

    async def test_set_playback_speed_preserves_elapsed_position(self) -> None:
        await self.controller.play(clip_id=7, single_clip=True)
        # Pretend playback has been running for 4 seconds.
        self.controller._play_started_at -= 4.0
        before = self.controller._clock_elapsed()

        ok = await self.controller.set_playback_speed(50)

        self.assertTrue(ok)
        # The clock keeps running between the two reads; only continuity matters.
        self.assertAlmostEqual(self.controller._clock_elapsed(), before, delta=0.1)

    async def test_set_playback_speed_requires_loaded_clip(self) -> None:
        ok = await self.controller.set_playback_speed(50)

        self.assertFalse(ok)
        self.assertEqual(self.player.speed_calls, [])

    async def test_cue_resets_speed_and_play_defaults_to_full_speed(self) -> None:
        await self.controller.play(clip_id=7, single_clip=True, speed=50)
        await self.controller.goto_clip(7)

        self.assertEqual(self.state.transport.playback_speed_percent, 100)

        await self.controller.play(clip_id=7, single_clip=True)

        self.assertEqual(self.state.transport.speed, 100)
        self.assertEqual(self.state.transport.playback_speed_percent, 100)

    async def test_stop_resets_speed(self) -> None:
        await self.controller.play(clip_id=7, single_clip=True, speed=150)

        await self.controller.stop_playback()

        self.assertEqual(self.state.transport.playback_speed_percent, 100)
        self.assertEqual(self.state.transport.speed, 0)

    async def test_cued_hold_then_play_starts_clock_at_in_point(self) -> None:
        # Regression: holding a cue before play used to double-count the hold
        # time and freeze the displayed timecode at the start of playback.
        self.clip_store.clips[7].mark_in_seconds = 2.0
        await self.controller.goto_clip(7)
        # Pretend the cue has been held for 30 seconds.
        self.controller._play_started_at -= 30.0
        self.controller._pause_started_at -= 30.0

        ok = await self.controller.play(clip_id=7, single_clip=True)

        self.assertTrue(ok)
        # The clock keeps running after play; the buggy behavior reported ~0.0 here.
        self.assertAlmostEqual(self.controller._clock_elapsed(), 2.0, delta=0.2)


if __name__ == '__main__':
    unittest.main()
