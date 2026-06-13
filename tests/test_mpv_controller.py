from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.config import AppConfig
from app.player.mpv_controller import MPVController


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

    async def test_seek_absolute_sends_time_pos_property_update(self) -> None:
        self.controller._reader = FakeReader(['{"request_id":1,"error":"success"}'])

        ok = await self.controller.seek_absolute(12.5)

        self.assertTrue(ok)
        payload = self.controller._writer.payloads[0].decode('utf-8')
        self.assertIn('"time-pos"', payload)
        self.assertIn('12.5', payload)
        self.assertIsNone(self.controller.last_error)

class MPVControllerAudioDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_audio_device_is_passed_at_startup(self) -> None:
        controller = MPVController(AppConfig(audio_device='alsa/sysdefault:CARD=Headphones'))

        _, command = controller._startup_profiles(Path('/tmp/mpv-test.log'))[0]

        self.assertIn('--audio-device=alsa/sysdefault:CARD=Headphones', command)

    async def test_auto_audio_device_adds_no_startup_flag(self) -> None:
        controller = MPVController(AppConfig())

        _, command = controller._startup_profiles(Path('/tmp/mpv-test.log'))[0]

        self.assertFalse(any(arg.startswith('--audio-device=') for arg in command))

    async def test_set_audio_device_updates_running_player(self) -> None:
        controller = MPVController(AppConfig())
        controller.process = SimpleNamespace(returncode=None)
        controller._writer = FakeWriter()
        controller._reader = FakeReader(['{"request_id":1,"error":"success"}'])

        ok = await controller.set_audio_device('alsa/sysdefault:CARD=vc4hdmi0')

        self.assertTrue(ok)
        self.assertEqual(controller.selected_audio_device, 'alsa/sysdefault:CARD=vc4hdmi0')
        payload = controller._writer.payloads[0].decode('utf-8')
        self.assertIn('"audio-device"', payload)
        self.assertIn('vc4hdmi0', payload)

    async def test_set_audio_device_is_remembered_while_player_is_down(self) -> None:
        controller = MPVController(AppConfig())

        ok = await controller.set_audio_device('alsa/sysdefault:CARD=Headphones')

        self.assertTrue(ok)
        _, command = controller._startup_profiles(Path('/tmp/mpv-test.log'))[0]
        self.assertIn('--audio-device=alsa/sysdefault:CARD=Headphones', command)

    async def test_hardware_mixer_boost_is_a_safe_noop_without_a_card(self) -> None:
        # 'auto' carries no CARD= token, so there is nothing to boost and the
        # call must never raise regardless of platform or amixer availability.
        controller = MPVController(AppConfig())

        await controller._maximize_hardware_mixer()

    async def test_list_audio_devices_parses_mpv_response(self) -> None:
        controller = MPVController(AppConfig())
        controller.process = SimpleNamespace(returncode=None)
        controller._writer = FakeWriter()
        controller._reader = FakeReader(
            [
                '{"request_id":1,"error":"success","data":['
                '{"name":"auto","description":"Autoselect device"},'
                '{"name":"alsa/sysdefault:CARD=vc4hdmi0","description":"vc4-hdmi-0"},'
                '{"name":"alsa/sysdefault:CARD=Headphones","description":"bcm2835 Headphones"}]}',
            ]
        )

        devices = await controller.list_audio_devices()

        self.assertEqual(
            [device['name'] for device in devices],
            ['auto', 'alsa/sysdefault:CARD=vc4hdmi0', 'alsa/sysdefault:CARD=Headphones'],
        )
        self.assertEqual(devices[2]['description'], 'bcm2835 Headphones')


if __name__ == '__main__':
    unittest.main()
