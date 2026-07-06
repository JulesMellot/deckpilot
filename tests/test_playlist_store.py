from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.core.config import AppConfig
from app.media.clip_store import ClipStore
from app.media.playlist_store import PlaylistStore


class PlaylistStoreRundownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base_path = Path(self.temp_dir.name)
        self.config = AppConfig(
            clips_dir=str(base_path / 'clips'),
            data_dir=str(base_path / 'data'),
            db_path=str(base_path / 'data' / 'test.db'),
            thumbnails_dir=str(base_path / 'thumbs'),
        )
        self.config.ensure_directories()
        self.clip_store = ClipStore(self.config)
        self.clip_store._initialize_sync()
        self.playlist_store = PlaylistStore(self.config.db_path, self.clip_store)
        self.playlist_store._initialize_sync()
        self.playlist_store._ensure_default_playlist_sync()
        for name in ('a.mp4', 'b.mp4', 'c.mp4'):
            (Path(self.config.clips_dir) / name).write_bytes(b'x')
        self.clip_store._sync_with_disk_sync()
        self.playlist_store._sync_active_playlist_from_clips_sync([1, 2, 3])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def active_playlist(self) -> dict:
        return asyncio.run(self.playlist_store.get_active_playlist())

    def active_id(self) -> int:
        return self.active_playlist()['playlist']['id']

    def test_default_playlist_mirrors_clips(self) -> None:
        items = self.active_playlist()['items']

        self.assertEqual([item['clip_id'] for item in items], [1, 2, 3])
        self.assertEqual([item['end_behavior'] for item in items], ['next', 'next', 'next'])

    def test_end_behavior_survives_mirror_resync(self) -> None:
        self.playlist_store._set_item_end_behavior_sync(self.active_id(), 2, 'hold')

        # A new clip lands in the library; the mirror playlist is rewritten.
        self.playlist_store._sync_active_playlist_from_clips_sync([1, 2, 3, 4])

        items = self.active_playlist()['items']
        self.assertEqual([item['clip_id'] for item in items], [1, 2, 3])  # clip 4 has no record yet
        self.assertEqual(items[1]['end_behavior'], 'hold')

    def test_set_item_end_behavior_rejects_unknown_value(self) -> None:
        result = asyncio.run(self.playlist_store.set_item_end_behavior(self.active_id(), 1, 'explode'))

        self.assertFalse(result)

    def test_remove_item_breaks_mirror_and_survives_resync(self) -> None:
        playlist_id = self.active_id()
        self.playlist_store._remove_item_from_playlist_sync(playlist_id, 2)

        self.playlist_store._sync_active_playlist_from_clips_sync([1, 2, 3])

        items = self.active_playlist()['items']
        self.assertEqual([item['clip_id'] for item in items], [1, 3])

    def test_clear_breaks_mirror_and_stays_empty(self) -> None:
        playlist_id = self.active_id()
        self.playlist_store._clear_playlist_sync(playlist_id)

        self.playlist_store._sync_active_playlist_from_clips_sync([1, 2, 3])

        self.assertEqual(self.active_playlist()['items'], [])

    def test_manual_playlist_prunes_deleted_clips(self) -> None:
        playlist_id = self.active_id()
        self.playlist_store._clear_playlist_sync(playlist_id)
        self.playlist_store._add_clip_to_playlist_sync(playlist_id, 1)
        self.playlist_store._add_clip_to_playlist_sync(playlist_id, 3)

        # Clip 3 disappears from the library.
        self.playlist_store._sync_active_playlist_from_clips_sync([1, 2])

        items = self.active_playlist()['items']
        self.assertEqual([item['clip_id'] for item in items], [1])

    def test_reorder_items_moves_positions(self) -> None:
        playlist_id = self.active_id()

        result = self.playlist_store._reorder_items_sync(playlist_id, [2, 1, 3])

        self.assertTrue(result)
        items = self.active_playlist()['items']
        self.assertEqual([item['clip_id'] for item in items], [2, 1, 3])

    def test_reorder_items_rejects_invalid_positions(self) -> None:
        self.assertFalse(self.playlist_store._reorder_items_sync(self.active_id(), [1, 1, 2]))

    def test_export_import_round_trip(self) -> None:
        playlist_id = self.active_id()
        self.playlist_store._set_item_end_behavior_sync(playlist_id, 1, 'loop')
        filenames = {1: 'a.mp4', 2: 'b.mp4', 3: 'c.mp4'}

        exported = self.playlist_store._export_playlists_sync(filenames)
        self.playlist_store._clear_playlist_sync(playlist_id)
        applied = self.playlist_store._apply_import_sync(exported, {'a.mp4': 1, 'b.mp4': 2, 'c.mp4': 3})

        self.assertEqual(applied, len(exported))
        items = self.active_playlist()['items']
        self.assertEqual([item['clip_id'] for item in items], [1, 2, 3])
        self.assertEqual(items[0]['end_behavior'], 'loop')

    def test_create_rename_and_get_non_active_playlist(self) -> None:
        created = asyncio.run(self.playlist_store.create_playlist('Musique matin', [2, 3]))

        self.assertTrue(asyncio.run(self.playlist_store.rename_playlist(created['id'], 'Jingles')))
        payload = asyncio.run(self.playlist_store.get_playlist(created['id']))

        self.assertEqual(payload['playlist']['name'], 'Jingles')
        self.assertFalse(payload['playlist']['is_active'])
        self.assertEqual([item['clip_id'] for item in payload['items']], [2, 3])
        # The active playlist did not change.
        self.assertNotEqual(self.active_id(), created['id'])

    def test_rename_rejects_empty_and_duplicate_names(self) -> None:
        created = asyncio.run(self.playlist_store.create_playlist('Jingles'))

        self.assertFalse(asyncio.run(self.playlist_store.rename_playlist(created['id'], '  ')))
        self.assertFalse(asyncio.run(self.playlist_store.rename_playlist(created['id'], 'Main Playlist')))

    def test_delete_playlist(self) -> None:
        created = asyncio.run(self.playlist_store.create_playlist('Jingles', [1]))

        self.assertTrue(asyncio.run(self.playlist_store.delete_playlist(created['id'])))
        self.assertFalse(asyncio.run(self.playlist_store.delete_playlist(created['id'])))
        payload = asyncio.run(self.playlist_store.get_playlist(created['id']))
        self.assertIsNone(payload['playlist'])

    def test_delete_active_playlist_falls_back_to_another(self) -> None:
        active_id = self.active_id()
        asyncio.run(self.playlist_store.create_playlist('Jingles', [1]))

        self.assertTrue(asyncio.run(self.playlist_store.delete_playlist(active_id)))

        payload = self.active_playlist()
        self.assertIsNotNone(payload['playlist'])
        self.assertNotEqual(payload['playlist']['id'], active_id)

    def test_music_flag_survives_mirror_resync(self) -> None:
        playlist_id = self.active_id()
        self.assertTrue(self.playlist_store._set_item_music_sync(playlist_id, 2, True))

        self.playlist_store._sync_active_playlist_from_clips_sync([1, 2, 3])

        items = self.active_playlist()['items']
        self.assertEqual([item['is_music'] for item in items], [False, True, False])

    def test_export_import_keeps_music_flag(self) -> None:
        playlist_id = self.active_id()
        self.playlist_store._set_item_music_sync(playlist_id, 3, True)
        filenames = {1: 'a.mp4', 2: 'b.mp4', 3: 'c.mp4'}

        exported = self.playlist_store._export_playlists_sync(filenames)
        self.playlist_store._clear_playlist_sync(playlist_id)
        self.playlist_store._apply_import_sync(exported, {'a.mp4': 1, 'b.mp4': 2, 'c.mp4': 3})

        items = self.active_playlist()['items']
        self.assertEqual([item['is_music'] for item in items], [False, False, True])

    def test_clip_level_music_flag_is_inherited_by_items(self) -> None:
        self.clip_store._set_music_sync(2, True)

        items = self.active_playlist()['items']

        self.assertEqual([item['is_music'] for item in items], [False, True, False])


if __name__ == '__main__':
    unittest.main()
