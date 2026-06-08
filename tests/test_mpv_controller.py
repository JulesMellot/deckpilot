from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from app.core.config import AppConfig
from app.player.mpv_controller import MPVController, _build_video_filter


class FakeWriter:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []
        self._closed = False

    def write(self, payload: bytes) -> None:
        self.payloads.append(payload)

    async def drain(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    async def wait_closed(self) -> None:
        return None


class FakeReader:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [f'{line}\n'.encode('utf-8') for line in lines]

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if not self._lines:
            return b''
        return self._lines.pop(0)


class MPVControllerCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.controller = MPVController(AppConfig())
        self.controller.process = SimpleNamespace(returncode=None)
        self.controller._writer = FakeWriter()

    async def test_command_ignores_async_events(self) -> None:
        self.controller._reader = FakeReader(
            [
                '{"event":"start-file"}',
                '{"request_id":1,"error":"success"}',
            ]
        )

        response = await self.controller.command(['loadfile', '/tmp/demo.mp4', 'replace'])

        self.assertIsNotNone(response)
        self.assertEqual(response['error'], 'success')
        self.assertIsNone(self.controller.last_error)

    async def test_command_waits_for_matching_request_id(self) -> None:
        self.controller._reader = FakeReader(
            [
                '{"request_id":999,"error":"success"}',
                '{"request_id":1,"error":"success"}',
            ]
        )

        response = await self.controller.command(['set_property', 'pause', False])

        self.assertIsNotNone(response)
        self.assertEqual(response['request_id'], 1)
        self.assertIsNone(self.controller.last_error)


class MPVControllerFilterTests(unittest.TestCase):
    def test_standard_filter_forces_16_9_canvas(self) -> None:
        vf = _build_video_filter('1080p25', is_vertical=False)

        self.assertIn('scale=1920:1080:force_original_aspect_ratio=decrease', vf)
        self.assertIn('pad=1920:1080', vf)
        self.assertIn('setsar=1', vf)

    def test_vertical_filter_builds_blurred_fill(self) -> None:
        vf = _build_video_filter('1080p25', is_vertical=True)

        self.assertIn('gblur=sigma=22', vf)
        self.assertIn('overlay=(W-w)/2:(H-h)/2', vf)
        self.assertIn('setsar=1', vf)


if __name__ == '__main__':
    unittest.main()
