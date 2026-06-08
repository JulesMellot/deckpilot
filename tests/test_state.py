from __future__ import annotations

import unittest

from app.core.config import AppConfig
from app.core.state import AppState


class AppStateSubscriberTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.state = AppState(AppConfig())

    async def test_publish_drops_oldest_events_for_slow_subscribers(self) -> None:
        queue = await self.state.subscribe()

        for value in range(70):
            await self.state.publish('tick', {'value': value})

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        self.assertEqual(len(events), 64)
        self.assertEqual(events[0]['payload']['value'], 6)
        self.assertEqual(events[-1]['payload']['value'], 69)

    async def test_unsubscribe_removes_queue_from_broadcasts(self) -> None:
        queue = await self.state.subscribe()
        await self.state.unsubscribe(queue)

        await self.state.publish('tick', {'value': 1})

        self.assertTrue(queue.empty())


if __name__ == '__main__':
    unittest.main()
