from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import AppConfig
from app.services.watch_folder import WatchFolderService


class FakeState:
    async def add_log(self, level: str, source: str, message: str) -> None:
        return None


class FakeController:
    def __init__(self) -> None:
        self.refresh_count = 0

    async def refresh_clips(self) -> None:
        self.refresh_count += 1


class WatchFolderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base_path = Path(self.temp_dir.name)
        self.config = AppConfig(
            clips_dir=str(base_path / 'clips'),
            data_dir=str(base_path / 'data'),
            db_path=str(base_path / 'data' / 'test.db'),
            thumbnails_dir=str(base_path / 'thumbs'),
        )
        self.config.ensure_directories()
        self.controller = FakeController()
        self.service = WatchFolderService(self.config, FakeState(), self.controller)
        self.service._ingested = await asyncio.to_thread(self.service._scan)
        self.service._last_scan = self.service._ingested

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_growing_file_is_not_ingested(self) -> None:
        clip = Path(self.config.clips_dir) / 'incoming.mp4'
        clip.write_bytes(b'partial')

        self.assertFalse(await self.service.tick())

        clip.write_bytes(b'partial-but-larger')

        self.assertFalse(await self.service.tick())
        self.assertEqual(self.controller.refresh_count, 0)

    async def test_stable_file_triggers_ingest_once(self) -> None:
        clip = Path(self.config.clips_dir) / 'incoming.mp4'
        clip.write_bytes(b'complete-file')

        self.assertFalse(await self.service.tick())  # first sight
        self.assertTrue(await self.service.tick())   # stable across two scans
        self.assertEqual(self.controller.refresh_count, 1)

        self.assertFalse(await self.service.tick())  # nothing new
        self.assertEqual(self.controller.refresh_count, 1)

    async def test_unsupported_extension_is_ignored(self) -> None:
        (Path(self.config.clips_dir) / 'notes.txt').write_text('hello')

        self.assertFalse(await self.service.tick())
        self.assertFalse(await self.service.tick())
        self.assertEqual(self.controller.refresh_count, 0)

    async def test_dotfiles_and_appledouble_are_ignored(self) -> None:
        (Path(self.config.clips_dir) / '._clip.mp4').write_bytes(b'apple-double-junk')
        (Path(self.config.clips_dir) / '.DS_Store').write_bytes(b'finder-junk')

        self.assertFalse(await self.service.tick())
        self.assertFalse(await self.service.tick())
        self.assertEqual(self.controller.refresh_count, 0)

    async def test_browned_out_usb_is_not_treated_as_mass_delete(self) -> None:
        usb_dir = Path(self.temp_dir.name) / 'usb'
        usb_dir.mkdir()
        (usb_dir / 'field.mp4').write_bytes(b'clip-on-the-stick')
        usb_path = str(usb_dir / 'field.mp4')

        with patch('app.services.watch_folder.removable_media_roots', return_value=[str(usb_dir)]):
            await self.service.tick()                       # first sight
            self.assertTrue(await self.service.tick())      # stable -> ingest
        self.assertIn(usb_path, self.service._ingested)
        refreshes = self.controller.refresh_count

        # The drive browns out and re-enumerates (no longer mounted): its file
        # must be retained, not reported as removed, and only a single refresh
        # fires for the drive going away.
        with patch('app.services.watch_folder.removable_media_roots', return_value=[]):
            await self.service.tick()
        self.assertIn(usb_path, self.service._ingested)
        self.assertEqual(self.controller.refresh_count, refreshes + 1)

    async def test_removed_file_triggers_refresh(self) -> None:
        clip = Path(self.config.clips_dir) / 'gone.mp4'
        clip.write_bytes(b'data')
        await self.service.tick()
        await self.service.tick()
        self.assertEqual(self.controller.refresh_count, 1)

        clip.unlink()

        self.assertFalse(await self.service.tick())
        self.assertTrue(await self.service.tick())
        self.assertEqual(self.controller.refresh_count, 2)


if __name__ == '__main__':
    unittest.main()
