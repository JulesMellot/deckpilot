from __future__ import annotations

import unittest

from app.core.config import AppConfig
from app.core.state import AppState
from app.services.deck_controller import DeckController, summarize_audio_devices


# Mirrors a real Raspberry Pi `audio-device-list`: HDMI and headphone cards each
# expose several PCMs, alongside pure software plugins that have no physical jack.
PI_AUDIO_DEVICES = [
    {'name': 'auto', 'description': 'Autoselect device'},
    {'name': 'alsa', 'description': 'Default (alsa)'},
    {'name': 'alsa/default', 'description': 'Default Audio Device'},
    {'name': 'alsa/lavrate', 'description': 'Rate Converter Plugin Using Libav/FFmpeg Library'},
    {'name': 'alsa/jack', 'description': 'JACK Audio Connection Kit'},
    {'name': 'alsa/oss', 'description': 'Open Sound System'},
    {'name': 'alsa/upmix', 'description': 'Plugin for channel upmix (4,6,8)'},
    {'name': 'alsa/sysdefault:CARD=vc4hdmi0', 'description': 'vc4-hdmi, MAI PCM i2s-hifi-0/Default Audio Device'},
    {'name': 'alsa/hdmi:CARD=vc4hdmi0,DEV=0', 'description': 'vc4-hdmi, MAI PCM i2s-hifi-0/HDMI Audio Output'},
    {'name': 'alsa/dmix:CARD=vc4hdmi0,DEV=0', 'description': 'vc4-hdmi, MAI PCM i2s-hifi-0/Direct sample mixing device'},
    {'name': 'alsa/sysdefault:CARD=Headphones', 'description': 'bcm2835 Headphones, bcm2835 Headphones/Default Audio Device'},
    {'name': 'alsa/plughw:CARD=Headphones,DEV=0', 'description': 'bcm2835 Headphones, bcm2835 Headphones/Hardware device with all software conversions'},
    {'name': 'alsa/dmix:CARD=Headphones,DEV=0', 'description': 'bcm2835 Headphones, bcm2835 Headphones/Direct sample mixing device'},
]


class SummarizeAudioDevicesTests(unittest.TestCase):
    def test_collapses_to_friendly_jacks(self) -> None:
        options = summarize_audio_devices(PI_AUDIO_DEVICES, 'auto')

        self.assertEqual([option['label'] for option in options], ['Auto', 'HDMI', 'Jack'])
        # Auto is the default selection and software plugins are dropped entirely.
        self.assertTrue(options[0]['selected'])

    def test_prefers_sysdefault_pcm_per_card(self) -> None:
        options = summarize_audio_devices(PI_AUDIO_DEVICES, 'auto')

        by_label = {option['label']: option['id'] for option in options}
        self.assertEqual(by_label['HDMI'], 'alsa/sysdefault:CARD=vc4hdmi0')
        self.assertEqual(by_label['Jack'], 'alsa/sysdefault:CARD=Headphones')

    def test_marks_selection_even_for_a_sibling_pcm(self) -> None:
        # A value saved by an older build (raw hardware PCM) still highlights Jack.
        options = summarize_audio_devices(PI_AUDIO_DEVICES, 'alsa/plughw:CARD=Headphones,DEV=0')

        jack = next(option for option in options if option['label'] == 'Jack')
        self.assertTrue(jack['selected'])
        self.assertFalse(options[0]['selected'])

    def test_numbers_multiple_ports_of_the_same_kind(self) -> None:
        devices = [
            {'name': 'alsa/sysdefault:CARD=vc4hdmi0', 'description': 'vc4-hdmi-0/Default Audio Device'},
            {'name': 'alsa/sysdefault:CARD=vc4hdmi1', 'description': 'vc4-hdmi-1/Default Audio Device'},
        ]

        options = summarize_audio_devices(devices, 'auto')

        self.assertEqual([option['label'] for option in options], ['Auto', 'HDMI 1', 'HDMI 2'])

    def test_keeps_unknown_hand_edited_value_visible(self) -> None:
        options = summarize_audio_devices(PI_AUDIO_DEVICES, 'alsa/custom-dac')

        custom = options[-1]
        self.assertEqual(custom['id'], 'alsa/custom-dac')
        self.assertTrue(custom['selected'])


class FakePlayer:
    def __init__(self) -> None:
        self.pause_calls: list[bool] = []
        self.last_error: str | None = None

    async def pause(self, enabled: bool = True) -> bool:
        self.pause_calls.append(enabled)
        return True


class DeckControllerPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.state = AppState(AppConfig())
        self.player = FakePlayer()
        self.controller = DeckController(
            config=AppConfig(),
            state=self.state,
            clip_store=object(),
            playlist_store=object(),
            output_manager=object(),
            network_info=object(),
            player=self.player,
        )

    async def test_preview_disable_pauses_active_playback(self) -> None:
        await self.state.set_transport(status='play', paused=False, speed=100, clip_id=3)

        await self.controller.set_preview_enabled(False)

        self.assertFalse(self.state.preview_enabled)
        self.assertEqual(self.player.pause_calls, [True])
        self.assertEqual(self.state.transport.status, 'stopped')
        self.assertTrue(self.state.transport.paused)
        self.assertEqual(self.state.transport.speed, 0)

    async def test_preview_disable_does_not_pause_when_not_playing(self) -> None:
        await self.state.set_transport(status='stopped', paused=False, speed=0, clip_id=3)

        await self.controller.set_preview_enabled(False)

        self.assertFalse(self.state.preview_enabled)
        self.assertEqual(self.player.pause_calls, [])

    async def test_preview_enable_does_not_pause(self) -> None:
        await self.state.set_transport(status='play', paused=False, speed=100, clip_id=3)

        await self.controller.set_preview_enabled(True)

        self.assertTrue(self.state.preview_enabled)
        self.assertEqual(self.player.pause_calls, [])
        self.assertEqual(self.state.transport.status, 'play')
        self.assertFalse(self.state.transport.paused)


class FakeCountdownClip:
    def __init__(self, deck_id: int, duration: float) -> None:
        self.deck_id = deck_id
        self.duration = duration

    def trim_bounds(self) -> tuple[float, float]:
        return (0.0, self.duration)


class FakeCountdownClipStore:
    def __init__(self, clips: list[FakeCountdownClip]) -> None:
        self.clips = clips

    async def list_clips(self) -> list[FakeCountdownClip]:
        return self.clips


class FakeCountdownPlaylistStore:
    def __init__(self, items: list[dict]) -> None:
        self.items = items

    async def get_active_playlist(self) -> dict:
        return {'playlist': {'id': 1}, 'items': self.items}


class PlaylistCountdownTests(unittest.IsolatedAsyncioTestCase):
    """The on-air countdown counts the auto-advance chain of videos after the
    current clip and stops before the first item flagged as music."""

    def make_controller(self, items: list[dict], clips: list[FakeCountdownClip]) -> DeckController:
        controller = DeckController(
            config=AppConfig(),
            state=AppState(AppConfig()),
            clip_store=FakeCountdownClipStore(clips),
            playlist_store=FakeCountdownPlaylistStore(items),
            output_manager=object(),
            network_info=object(),
            player=FakePlayer(),
        )
        controller._playlist_mode = True
        return controller

    async def test_countdown_sums_videos_until_music(self) -> None:
        items = [
            {'position': 1, 'clip_id': 1, 'end_behavior': 'next', 'is_music': False},
            {'position': 2, 'clip_id': 2, 'end_behavior': 'next', 'is_music': False},
            {'position': 3, 'clip_id': 3, 'end_behavior': 'next', 'is_music': True},
            {'position': 4, 'clip_id': 4, 'end_behavior': 'next', 'is_music': False},
        ]
        clips = [FakeCountdownClip(1, 10.0), FakeCountdownClip(2, 20.0), FakeCountdownClip(3, 180.0), FakeCountdownClip(4, 40.0)]
        controller = self.make_controller(items, clips)

        await controller._refresh_playlist_countdown(1)

        # Playing clip 1 with 5s left: only clip 2 counts, the music stops the chain.
        self.assertEqual(controller._countdown_for(5.0), 25.0)

    async def test_countdown_is_zero_while_music_plays(self) -> None:
        items = [
            {'position': 1, 'clip_id': 1, 'end_behavior': 'next', 'is_music': True},
            {'position': 2, 'clip_id': 2, 'end_behavior': 'next', 'is_music': False},
        ]
        clips = [FakeCountdownClip(1, 180.0), FakeCountdownClip(2, 20.0)]
        controller = self.make_controller(items, clips)

        await controller._refresh_playlist_countdown(1)

        self.assertEqual(controller._countdown_for(90.0), 0.0)

    async def test_countdown_chain_stops_after_a_stop_item(self) -> None:
        items = [
            {'position': 1, 'clip_id': 1, 'end_behavior': 'next', 'is_music': False},
            {'position': 2, 'clip_id': 2, 'end_behavior': 'stop', 'is_music': False},
            {'position': 3, 'clip_id': 3, 'end_behavior': 'next', 'is_music': False},
        ]
        clips = [FakeCountdownClip(1, 10.0), FakeCountdownClip(2, 20.0), FakeCountdownClip(3, 40.0)]
        controller = self.make_controller(items, clips)

        await controller._refresh_playlist_countdown(1)

        # Clip 2 plays then stops: clip 3 never airs on its own, so it is not counted.
        self.assertEqual(controller._countdown_for(5.0), 25.0)

    async def test_countdown_only_covers_current_clip_when_it_does_not_advance(self) -> None:
        items = [
            {'position': 1, 'clip_id': 1, 'end_behavior': 'hold', 'is_music': False},
            {'position': 2, 'clip_id': 2, 'end_behavior': 'next', 'is_music': False},
        ]
        clips = [FakeCountdownClip(1, 10.0), FakeCountdownClip(2, 20.0)]
        controller = self.make_controller(items, clips)

        await controller._refresh_playlist_countdown(1)

        self.assertEqual(controller._countdown_for(5.0), 5.0)

    async def test_countdown_matches_remaining_outside_playlist_mode(self) -> None:
        controller = self.make_controller([], [])
        controller._playlist_mode = False

        await controller._refresh_playlist_countdown(1)

        self.assertEqual(controller._countdown_for(7.5), 7.5)


if __name__ == '__main__':
    unittest.main()
