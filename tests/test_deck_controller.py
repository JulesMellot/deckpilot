from __future__ import annotations

import unittest

from app.core.config import AppConfig
from app.core.state import AppState
from app.services.deck_controller import DeckController


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


if __name__ == '__main__':
    unittest.main()
