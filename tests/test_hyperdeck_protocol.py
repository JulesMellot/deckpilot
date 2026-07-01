from __future__ import annotations

import asyncio
import contextlib
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

    def get_extra_info(self, _name: str):
        return ('127.0.0.1', 1)

    async def wait_closed(self) -> None:
        return None


class FakeReader:
    """Feeds canned lines, then EOF, like asyncio.StreamReader."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    def at_eof(self) -> bool:
        return not self._lines

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b''


class FlakyReader:
    """Feeds a scripted mix of lines and readline() errors, then EOF."""

    def __init__(self, script: list) -> None:
        # Each item is either bytes (a line) or an exception class to raise.
        self._script = list(script)

    def at_eof(self) -> bool:
        return not self._script

    async def readline(self) -> bytes:
        if not self._script:
            return b''
        item = self._script.pop(0)
        if isinstance(item, type) and issubclass(item, Exception):
            raise item('line too long')
        return item


def _make_server(clips: list | None = None):
    config = AppConfig()
    state = AppState(config)
    controller = DeckController(
        config=config, state=state, clip_store=FakeClipStore(clips or []),
        playlist_store=FakePlaylistStore(), output_manager=FakeOutputManager(),
        network_info=FakeNetworkInfo(), player=FakePlayer(),
    )
    return HyperDeckServer(config, state, controller), state, controller


class HyperDeckMultilineTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiline_block_is_folded_into_one_command(self) -> None:
        config = AppConfig()
        state = AppState(config)
        controller = DeckController(
            config=config, state=state, clip_store=FakeClipStore([]),
            playlist_store=FakePlaylistStore(), output_manager=FakeOutputManager(),
            network_info=FakeNetworkInfo(), player=FakePlayer(),
        )
        server = HyperDeckServer(config, state, controller)
        # Companion's multi-line form: header, params, blank-line terminator.
        reader = FakeReader([
            b'watchdog:\r\n', b'period: 6\r\n', b'\r\n',
            b'notify:\r\n', b'remote: true\r\n', b'transport: true\r\n', b'\r\n',
        ])
        writer = FakeWriter()
        await server._handle_client(reader, writer)
        # No 100 syntax error went out, and the blocks took effect.
        self.assertNotIn(b'100 syntax error', writer.data)


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

    async def test_clips_count_returns_214_with_clip_count(self) -> None:
        reply = await self.dispatch('clips count')

        self.assertTrue(reply.startswith('214 clips count:'))
        self.assertIn('clip count: 3', reply)

    async def test_transport_info_includes_single_clip_and_loop(self) -> None:
        reply = await self.dispatch('transport info')

        self.assertTrue(reply.startswith('208 transport info:'))
        self.assertIn('single clip: false', reply)
        self.assertIn('loop: false', reply)

    async def test_transport_info_advertises_first_clip_when_idle(self) -> None:
        # Nothing cued: the ATEM needs a non-zero clip id to arm auto-roll.
        reply = await self.dispatch('transport info')

        self.assertIn('clip id: 1', reply)

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

    async def test_bare_remote_returns_210_not_200(self) -> None:
        # Companion sends `remote` as a query and expects 210 remote info.
        reply = await self.dispatch('remote')
        self.assertTrue(reply.startswith('210 remote info:'))
        self.assertIn('enabled:', reply)

    async def test_remote_enable_sets_and_returns_210(self) -> None:
        reply = await self.dispatch('remote: enable: false')
        self.assertTrue(reply.startswith('210 remote info:'))
        self.assertIn('enabled: false', reply)

    async def test_watchdog_acks_and_stores_period(self) -> None:
        # Companion arms this on connect; a 100 syntax error here drops the link.
        reply = await self.dispatch('watchdog: period: 6')
        self.assertTrue(reply.startswith('200 ok'))
        self.assertEqual(self.session.watchdog_period, 6)

    async def test_play_with_invalid_speed_returns_102(self) -> None:
        await self.controller.goto_clip(1)

        self.assertTrue((await self.dispatch('play: speed: fast')).startswith('102 invalid value'))
        self.assertTrue((await self.dispatch('play: speed: -100')).startswith('102 invalid value'))

    async def test_clips_add_non_numeric_id_returns_102(self) -> None:
        # A garbage clip id must not raise and drop the connection.
        self.assertTrue((await self.dispatch('clips add: clip id: abc')).startswith('102 invalid value'))

    async def test_slot_select_non_numeric_id_returns_102(self) -> None:
        self.assertTrue((await self.dispatch('slot select: slot id: xyz')).startswith('102 invalid value'))

    async def test_playrange_set_non_numeric_id_returns_102(self) -> None:
        self.assertTrue((await self.dispatch('playrange set: clip id: nope')).startswith('102 invalid value'))


class HyperDeckRobustnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_line_resyncs_without_dropping_connection(self) -> None:
        # asyncio's readline() raises ValueError on a >64KB line; the server must
        # swallow it, resync, and still answer the next command.
        server, _state, _controller = _make_server()
        reader = FlakyReader([ValueError, b'ping\r\n'])
        writer = FakeWriter()

        await server._handle_client(reader, writer)

        self.assertIn(b'200 ok', writer.data)
        self.assertTrue(writer.closed)

    async def test_transport_notify_never_advertises_clip_zero(self) -> None:
        clips = [FakeClip(deck_id=1, name='Intro', filepath='/tmp/intro.mp4')]
        server, state, _controller = _make_server(clips)
        server._queue = await state.subscribe()
        session = HyperDeckSession(key='n', writer=FakeWriter(), host='127.0.0.1', port=1)
        session.notify_transport = True
        server.sessions[session.key] = session
        task = asyncio.create_task(server._broadcast_events())
        try:
            # Idle transport change (clip id still 0): the async 508 must fall
            # back to the first clip, matching the synchronous transport info.
            await state.set_transport(status='stopped', speed=1)
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.assertIn(b'clip id: 1', session.writer.data)
        self.assertNotIn(b'clip id: 0', session.writer.data)


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
