from __future__ import annotations

import unittest

from app.core.config import AppConfig
from app.core.state import AppState
from app.hyperdeck.protocol import parse_command, timecode_to_seconds
from app.hyperdeck.server import HyperDeckServer, HyperDeckSession
from app.services.deck_controller import DeckController
from tests.test_cue_loop import (
    FakeClip,
    FakeClipStore,
    FakeNetworkInfo,
    FakeOutputManager,
    FakePlayer,
    FakePlaylistStore,
)


class FakeWriter:
    def __init__(self) -> None:
        self.data = b''
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.data += payload

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class HyperDeckDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clips = [
            FakeClip(deck_id=1, name='Intro', filepath='/tmp/intro.mp4'),
            FakeClip(deck_id=2, name='Main', filepath='/tmp/main.mp4'),
            FakeClip(deck_id=3, name='Outro', filepath='/tmp/outro.mp4'),
        ]
        self.config = AppConfig()
        self.state = AppState(self.config)
        self.player = FakePlayer()
        self.controller = DeckController(
            config=self.config,
            state=self.state,
            clip_store=FakeClipStore(clips),
            playlist_store=FakePlaylistStore(),
            output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(),
            player=self.player,
        )
        self.server = HyperDeckServer(self.config, self.state, self.controller)
        self.session = HyperDeckSession(key='t', writer=FakeWriter(), host='127.0.0.1', port=1)

    async def dispatch(self, line: str) -> str:
        reply = await self.server._dispatch(self.session, line)
        return (reply or b'').decode('utf-8')

    async def test_unknown_command_returns_100_syntax_error(self) -> None:
        self.assertTrue((await self.dispatch('frobnicate')).startswith('100 syntax error'))

    async def test_remote_disabled_returns_111(self) -> None:
        await self.state.set_remote_enabled(False)

        self.assertTrue((await self.dispatch('play')).startswith('111 remote control disabled'))

    async def test_device_info_exposes_slot_count_and_versions(self) -> None:
        reply = await self.dispatch('device info')

        self.assertTrue(reply.startswith('204 device info:'))
        self.assertIn('protocol version: 1.11', reply)
        self.assertIn('slot count: 1', reply)
        self.assertIn('software version:', reply)

    async def test_clips_get_uses_start_and_duration_timecodes(self) -> None:
        reply = await self.dispatch('clips get')

        self.assertIn('clip count: 3', reply)
        self.assertIn('1: Intro 00:00:00:00 00:00:12:00', reply)

    async def test_transport_info_includes_single_clip_and_loop(self) -> None:
        reply = await self.dispatch('transport info')

        self.assertTrue(reply.startswith('208 transport info:'))
        self.assertIn('single clip: false', reply)
        self.assertIn('loop: false', reply)

    async def test_goto_relative_clip_id_moves_from_current(self) -> None:
        await self.controller.goto_clip(2)

        reply = await self.dispatch('goto: clip id: +1')

        self.assertTrue(reply.startswith('200 ok'))
        self.assertEqual(self.state.transport.clip_id, 3)

        reply = await self.dispatch('goto: clip id: -2')
        self.assertTrue(reply.startswith('200 ok'))
        self.assertEqual(self.state.transport.clip_id, 1)

    async def test_goto_absolute_clip_id_still_works(self) -> None:
        reply = await self.dispatch('goto: clip id: 2')

        self.assertTrue(reply.startswith('200 ok'))
        self.assertEqual(self.state.transport.clip_id, 2)

    async def test_goto_unknown_clip_returns_112(self) -> None:
        self.assertTrue((await self.dispatch('goto: clip id: 99')).startswith('112 clip not found'))

    async def test_goto_timecode_seeks_current_clip(self) -> None:
        await self.controller.goto_clip(1)

        reply = await self.dispatch('goto: timecode: 00:00:04:00')

        self.assertTrue(reply.startswith('200 ok'))
        self.assertAlmostEqual(self.player.seek_calls[-1], 4.0, places=2)

    async def test_notify_query_returns_209_with_flags(self) -> None:
        reply = await self.dispatch('notify')

        self.assertTrue(reply.startswith('209 notify:'))
        self.assertIn('transport: false', reply)

        await self.dispatch('notify: transport: true remote: true')
        reply = await self.dispatch('notify')
        self.assertIn('transport: true', reply)
        self.assertIn('remote: true', reply)

    async def test_notifications_are_disabled_by_default(self) -> None:
        self.assertFalse(self.session.notify_transport)
        self.assertFalse(self.session.notify_slot)
        self.assertFalse(self.session.notify_clips)
        self.assertFalse(self.session.notify_remote)

    async def test_remote_info_uses_code_210_with_override(self) -> None:
        reply = await self.dispatch('remote info')

        self.assertTrue(reply.startswith('210 remote info:'))
        self.assertIn('enabled: true', reply)
        self.assertIn('override: false', reply)

    async def test_play_with_invalid_speed_returns_102(self) -> None:
        await self.controller.goto_clip(1)

        self.assertTrue((await self.dispatch('play: speed: fast')).startswith('102 invalid value'))
        self.assertTrue((await self.dispatch('play: speed: -100')).startswith('102 invalid value'))


class ProtocolHelperTests(unittest.TestCase):
    def test_parse_command_with_multiword_command(self) -> None:
        command, params = parse_command('clips add: clip id: 5')

        self.assertEqual(command, 'clips add')
        self.assertEqual(params.get('clip id'), '5')

    def test_timecode_to_seconds(self) -> None:
        self.assertAlmostEqual(timecode_to_seconds('00:01:10:12', 25.0), 70.48, places=2)
        self.assertAlmostEqual(timecode_to_seconds('+00:00:05:00', 25.0), 5.0, places=2)
        self.assertAlmostEqual(timecode_to_seconds('-00:00:05:00', 25.0), -5.0, places=2)
        self.assertIsNone(timecode_to_seconds('garbage', 25.0))


if __name__ == '__main__':
    unittest.main()
