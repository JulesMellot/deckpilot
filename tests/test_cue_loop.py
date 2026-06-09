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
    async def sync_active_playlist_from_clips(self) -> None:
        return None

    async def list_playlists(self) -> list[dict]:
        return []

    async def get_active_playlist(self) -> dict:
        return {'playlist': None, 'items': []}

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


if __name__ == '__main__':
    unittest.main()
