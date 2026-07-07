from __future__ import annotations

import asyncio
import io
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import AppConfig
from app.media.clip_store import ClipStore, normalize_tags, parse_rms_levels


class ClipStoreThumbnailTests(unittest.TestCase):
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
        self.store = ClipStore(self.config)
        self.store._initialize_sync()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_thumbnail_output_path_is_unique_for_different_filenames(self) -> None:
        clip_a = Path(self.config.clips_dir) / 'demo.mp4'
        clip_b = Path(self.config.clips_dir) / 'demo.mov'
        clip_a.write_bytes(b'a')
        clip_b.write_bytes(b'b')

        path_a = self.store._thumbnail_output_path(clip_a)
        path_b = self.store._thumbnail_output_path(clip_b)

        self.assertNotEqual(path_a, path_b)
        self.assertTrue(path_a.name.endswith('.jpg'))
        self.assertTrue(path_b.name.endswith('.jpg'))

    def test_thumbnail_needs_refresh_is_false_for_existing_fresh_thumbnail(self) -> None:
        clip = Path(self.config.clips_dir) / 'demo.mp4'
        clip.write_bytes(b'video-data')
        thumb_path = self.store._thumbnail_output_path(clip)
        thumb_path.write_bytes(b'image-data')
        source_mtime = clip.stat().st_mtime_ns
        os.utime(thumb_path, ns=(source_mtime + 1_000_000, source_mtime + 1_000_000))

        self.assertFalse(self.store._thumbnail_needs_refresh(clip, str(thumb_path)))

    def test_thumbnail_needs_refresh_when_source_changes(self) -> None:
        clip = Path(self.config.clips_dir) / 'demo.mp4'
        clip.write_bytes(b'video-data')
        stale_thumb = self.store._thumbnail_output_path(clip)
        stale_thumb.write_bytes(b'image-data')

        updated_source_time = clip.stat().st_mtime_ns + 5_000_000
        clip.write_bytes(b'updated-video-data')
        os.utime(clip, ns=(updated_source_time, updated_source_time))

        self.assertTrue(self.store._thumbnail_needs_refresh(clip, str(stale_thumb)))

    def test_sync_inserts_placeholder_record_and_defers_enrichment(self) -> None:
        clip = Path(self.config.clips_dir) / 'placeholder.mp4'
        clip.write_bytes(b'video-data')

        self.store._probe_clip = lambda _: self.fail('sync should not probe during fast ingest')
        self.store._generate_thumbnail = lambda _: self.fail('sync should not generate thumbnails during fast ingest')

        pending = self.store._sync_with_disk_sync()
        clips = self.store._list_clips_sync()

        self.assertEqual(pending, [str(clip)])
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].filename, 'placeholder.mp4')
        self.assertEqual(clips[0].duration_seconds, 0.0)
        self.assertEqual(clips[0].thumbnail_path, None)
        self.assertEqual(clips[0].codec, 'unknown')
        self.assertEqual(clips[0].media_kind, 'video')
        self.assertEqual(clips[0].processing_state, 'pending')

    def test_processing_error_stores_reason_and_clears_it_on_retry(self) -> None:
        clip = Path(self.config.clips_dir) / 'broken.mp4'
        clip.write_bytes(b'not-really-video')
        self.store._sync_with_disk_sync()

        self.store._set_processing_state_sync('broken.mp4', 'error', 'Unreadable file — no video stream found')
        errored = self.store._list_clips_sync()[0]
        self.assertEqual(errored.processing_state, 'error')
        self.assertEqual(errored.error_reason, 'Unreadable file — no video stream found')

        # Re-processing (any non-error state) must drop the stale reason.
        self.store._set_processing_state_sync('broken.mp4', 'processing')
        retried = self.store._list_clips_sync()[0]
        self.assertEqual(retried.error_reason, '')

    def test_sync_ingests_usb_clips_and_marks_them_offline_when_unplugged(self) -> None:
        usb_dir = Path(self.temp_dir.name) / 'usb'
        usb_dir.mkdir()
        internal_clip = Path(self.config.clips_dir) / 'house.mp4'
        usb_clip = usb_dir / 'field.mp4'
        internal_clip.write_bytes(b'a')
        usb_clip.write_bytes(b'b')

        with patch('app.media.clip_store.removable_media_roots', return_value=[str(usb_dir)]):
            self.store._sync_with_disk_sync()
            clips = {c.filename: c for c in self.store._list_clips_sync()}

        self.assertEqual(set(clips), {'house.mp4', 'field.mp4'})
        self.assertEqual(clips['house.mp4'].source, 'Internal')
        self.assertTrue(clips['house.mp4'].available)
        self.assertEqual(clips['field.mp4'].source, 'usb')
        self.assertTrue(clips['field.mp4'].available)
        self.assertEqual(clips['field.mp4'].filepath, str(usb_clip))

        # Unplug the drive: the USB clip stays in the library but goes offline,
        # while the internal clip is untouched.
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
            clips = {c.filename: c for c in self.store._list_clips_sync()}

        self.assertEqual(set(clips), {'house.mp4', 'field.mp4'})
        self.assertFalse(clips['field.mp4'].available)
        self.assertTrue(clips['house.mp4'].available)

    def test_sync_deletes_clip_removed_from_a_connected_disk(self) -> None:
        internal_clip = Path(self.config.clips_dir) / 'gone.mp4'
        internal_clip.write_bytes(b'a')
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
            self.assertEqual(len(self.store._list_clips_sync()), 1)
            internal_clip.unlink()
            self.store._sync_with_disk_sync()
            self.assertEqual(len(self.store._list_clips_sync()), 0)

    def test_sync_ignores_dotfiles_and_appledouble(self) -> None:
        (Path(self.config.clips_dir) / 'real.mp4').write_bytes(b'a')
        (Path(self.config.clips_dir) / '._real.mp4').write_bytes(b'apple-double')
        (Path(self.config.clips_dir) / '.DS_Store').write_bytes(b'finder')
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
        clips = self.store._list_clips_sync()
        self.assertEqual([c.filename for c in clips], ['real.mp4'])

    def test_sync_keeps_clips_when_a_connected_root_fails_to_scan(self) -> None:
        (Path(self.config.clips_dir) / 'house.mp4').write_bytes(b'a')
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
        self.assertEqual(len(self.store._list_clips_sync()), 1)

        # Simulate a pass where no root could be read (e.g. a transient I/O
        # error): nothing must be deleted.
        with patch.object(self.store, '_scan_source_files', return_value=([], [])):
            self.store._sync_with_disk_sync()
        self.assertEqual(len(self.store._list_clips_sync()), 1)

    def test_set_folder_by_filenames_places_uploads_in_current_folder(self) -> None:
        for name in ('intro.mp4', 'demo.webm'):
            (Path(self.config.clips_dir) / name).write_bytes(b'x')
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
        self.store._set_folder_by_filenames_sync(['intro.mp4', 'demo.webm'], 'Events')
        folders = {c.filename: c.folder for c in self.store._list_clips_sync()}
        self.assertEqual(folders['intro.mp4'], 'Events')
        self.assertEqual(folders['demo.webm'], 'Events')
        self.assertIn('Events', self.store._list_folders_sync())

    def test_set_folder_by_filenames_ignores_default_bucket(self) -> None:
        (Path(self.config.clips_dir) / 'a.mp4').write_bytes(b'x')
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
        self.store._set_folder_by_filenames_sync(['a.mp4'], 'All')
        self.store._set_folder_by_filenames_sync(['a.mp4'], 'Library')
        self.assertEqual(self.store._list_clips_sync()[0].folder, 'Library')

    def test_bulk_delete_by_filename_removes_only_named_clips(self) -> None:
        for name in ('a.mp4', 'b.mp4', 'c.mp4'):
            (Path(self.config.clips_dir) / name).write_bytes(b'x')
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            self.store._sync_with_disk_sync()
        deleted = self.store._delete_clips_by_filenames_sync(['a.mp4', 'c.mp4', 'ghost.mp4'])
        remaining = sorted(c.filename for c in self.store._list_clips_sync())
        self.assertEqual(deleted, 2)
        self.assertEqual(remaining, ['b.mp4'])
        self.assertFalse((Path(self.config.clips_dir) / 'a.mp4').exists())
        self.assertTrue((Path(self.config.clips_dir) / 'b.mp4').exists())

    def test_bulk_delete_handles_empty_and_offline_entries(self) -> None:
        # A remote link has no local file; deleting it must not raise.
        key, _ = self.store._insert_remote_clip_sync('https://cdn.example.com/v.mp4', None)
        self.assertEqual(self.store._delete_clips_by_filenames_sync([]), 0)
        self.assertEqual(self.store._delete_clips_by_filenames_sync([key]), 1)
        self.assertEqual(self.store._list_clips_sync(), [])

    def test_remote_clip_is_inserted_as_link_source(self) -> None:
        key, url = self.store._insert_remote_clip_sync('https://cdn.example.com/live/stream.m3u8', None)
        clips = self.store._list_clips_sync()
        self.assertEqual(len(clips), 1)
        clip = clips[0]
        self.assertTrue(clip.is_remote)
        self.assertEqual(clip.source, 'Link')
        self.assertTrue(clip.available)
        self.assertEqual(clip.filepath, url)
        self.assertEqual(clip.name, 'stream.m3u8')

    def test_remote_clip_rejects_non_url_and_duplicates(self) -> None:
        with self.assertRaises(ValueError):
            self.store._insert_remote_clip_sync('/home/pi/clip.mp4', None)
        self.store._insert_remote_clip_sync('rtsp://cam.local/stream', 'Lobby Cam')
        with self.assertRaises(ValueError):
            self.store._insert_remote_clip_sync('rtsp://cam.local/stream', 'Lobby Cam')

    def test_disk_sync_never_deletes_remote_clips(self) -> None:
        self.store._insert_remote_clip_sync('https://cdn.example.com/vod.mp4', None)
        with patch('app.media.clip_store.removable_media_roots', return_value=[]):
            # A disk sync with no matching file on disk must keep the link.
            self.store._sync_with_disk_sync()
        clips = self.store._list_clips_sync()
        self.assertEqual(len(clips), 1)
        self.assertTrue(clips[0].is_remote)

    def test_remote_clip_is_not_served_over_media(self) -> None:
        key, _ = self.store._insert_remote_clip_sync('https://cdn.example.com/vod.mp4', None)
        self.assertIsNone(self.store._path_for_filename_sync(key))

    def test_sync_detects_image_placeholder_kind(self) -> None:
        clip = Path(self.config.clips_dir) / 'still.jpg'
        clip.write_bytes(b'image-data')

        pending = self.store._sync_with_disk_sync()
        clips = self.store._list_clips_sync()

        self.assertEqual(pending, [str(clip)])
        self.assertEqual(clips[0].media_kind, 'image')

    def test_enrich_clip_sync_updates_placeholder_record(self) -> None:
        clip = Path(self.config.clips_dir) / 'enrich.mp4'
        clip.write_bytes(b'video-data')
        self.store._sync_with_disk_sync()

        thumb_path = Path(self.config.thumbnails_dir) / 'enrich-thumb.jpg'
        thumb_path.write_bytes(b'image-data')
        self.store._probe_clip = lambda _: {
            'duration_seconds': 12.0,
            'duration_timecode': '00:00:12:00',
            'framerate': 25.0,
            'codec': 'h264',
            'width': 1920,
            'height': 1080,
            'is_vertical': False,
        }
        self.store._generate_thumbnail = lambda _: str(thumb_path)

        changed = self.store._enrich_clip_sync(clip)
        clips = self.store._list_clips_sync()

        self.assertTrue(changed)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].duration_seconds, 12.0)
        self.assertEqual(clips[0].duration_timecode, '00:00:12:00')
        self.assertEqual(clips[0].thumbnail_path, str(thumb_path))
        self.assertEqual(clips[0].codec, 'h264')
        self.assertEqual(clips[0].processing_state, 'ready')

    def test_image_without_thumbnail_needs_refresh(self) -> None:
        # Stills now get real thumbnails for the media grid.
        image = Path(self.config.clips_dir) / 'poster.png'
        image.write_bytes(b'image-data')

        self.assertTrue(self.store._thumbnail_needs_refresh(image, None))

    def test_probe_clip_applies_default_duration_to_images(self) -> None:
        image = Path(self.config.clips_dir) / 'poster.jpg'
        image.write_bytes(b'image-data')

        with patch('app.media.clip_store.shutil.which', return_value='/usr/bin/ffprobe'):
            with patch('app.media.clip_store.subprocess.run') as mock_run:
                mock_run.return_value.stdout = '\n'.join([
                    'codec_name=mjpeg',
                    'width=1920',
                    'height=1080',
                    'duration=N/A',
                ])
                meta = self.store._probe_clip(image)

        self.assertEqual(meta['media_kind'], 'image')
        self.assertEqual(meta['codec'], 'mjpeg')
        self.assertEqual(meta['duration_seconds'], self.config.default_image_duration_seconds)
        self.assertEqual(meta['duration_timecode'], '00:00:10:00')

    def test_processing_status_counts_pending_processing_and_error(self) -> None:
        with self.store._connect() as conn:
            conn.execute(
                """
                INSERT INTO clips (
                    sort_order, name, folder, filename, filepath, duration_seconds, duration_timecode,
                    framerate, codec, width, height, is_vertical, thumbnail_path, processing_state, loop_enabled, is_builtin
                ) VALUES
                    (1, 'Pending', 'Library', 'pending.mp4', '/tmp/pending.mp4', 0, '00:00:00:00', 25, 'unknown', 0, 0, 0, NULL, 'pending', 0, 0),
                    (2, 'Processing', 'Library', 'processing.mp4', '/tmp/processing.mp4', 0, '00:00:00:00', 25, 'unknown', 0, 0, 0, NULL, 'processing', 0, 0),
                    (3, 'Ready', 'Library', 'ready.mp4', '/tmp/ready.mp4', 10, '00:00:10:00', 25, 'h264', 1920, 1080, 0, NULL, 'ready', 0, 0),
                    (4, 'Error', 'Library', 'error.mp4', '/tmp/error.mp4', 0, '00:00:00:00', 25, 'unknown', 0, 0, 0, NULL, 'error', 0, 0)
                """
            )
            conn.commit()

        status = self.store._processing_status_sync()

        self.assertEqual(status['pending'], 1)
        self.assertEqual(status['processing'], 1)
        self.assertEqual(status['ready'], 1)
        self.assertEqual(status['error'], 1)
        self.assertIsNone(status['eta_seconds'])

    def test_processing_status_estimates_eta_from_completed_batch_progress(self) -> None:
        with self.store._connect() as conn:
            conn.execute(
                """
                INSERT INTO clips (
                    sort_order, name, folder, filename, filepath, duration_seconds, duration_timecode,
                    framerate, codec, width, height, is_vertical, thumbnail_path, processing_state, loop_enabled, is_builtin
                ) VALUES
                    (1, 'Pending A', 'Library', 'pending-a.mp4', '/tmp/pending-a.mp4', 0, '00:00:00:00', 25, 'unknown', 0, 0, 0, NULL, 'pending', 0, 0),
                    (2, 'Pending B', 'Library', 'pending-b.mp4', '/tmp/pending-b.mp4', 0, '00:00:00:00', 25, 'unknown', 0, 0, 0, NULL, 'pending', 0, 0)
                """
            )
            conn.commit()

        self.store._processing_batch_started_at = time.monotonic() - 2.0
        self.store._processing_batch_total = 4
        self.store._processing_batch_completed = 2

        status = self.store._processing_status_sync()

        self.assertGreater(status['clips_per_second'], 0)
        self.assertIsNotNone(status['eta_seconds'])
        self.assertLess(status['eta_seconds'], 5.0)

    def test_save_upload_streams_copies_file_objects_to_disk(self) -> None:
        class DummyUpload:
            def __init__(self, filename: str, content: bytes) -> None:
                self.filename = filename
                self.file = io.BytesIO(content)

        uploads = [DummyUpload('streamed.mp4', b'stream-data')]

        import asyncio

        asyncio.run(self.store.save_upload_streams(uploads))

        saved = Path(self.config.clips_dir) / 'streamed.mp4'
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), b'stream-data')

    def test_set_tags_normalizes_and_persists(self) -> None:
        (Path(self.config.clips_dir) / 'demo.mp4').write_bytes(b'a')
        self.store._sync_with_disk_sync()

        self.store._set_tags_sync(1, normalize_tags('Sport,  Replay , sport'))

        clip = self.store._list_clips_sync()[0]
        self.assertEqual(clip.tags, 'sport, replay')

    def test_set_duration_updates_seconds_and_timecode(self) -> None:
        (Path(self.config.clips_dir) / 'poster.png').write_bytes(b'a')
        self.store._sync_with_disk_sync()

        self.store._set_duration_sync(1, 7.0)

        clip = self.store._list_clips_sync()[0]
        self.assertEqual(clip.duration_seconds, 7.0)
        self.assertEqual(clip.duration_timecode, '00:00:07:00')

    def test_apply_import_entries_matches_by_filename(self) -> None:
        (Path(self.config.clips_dir) / 'demo.mp4').write_bytes(b'a')
        (Path(self.config.clips_dir) / 'other.mp4').write_bytes(b'b')
        self.store._sync_with_disk_sync()

        applied = self.store._apply_import_entries_sync([
            {
                'filename': 'demo.mp4',
                'name': 'Opening Loop',
                'folder': 'Show',
                'loop_enabled': True,
                'mark_in_seconds': 1.5,
                'mark_out_seconds': 9.0,
                'tags': 'intro, loop',
            },
            {'filename': 'missing.mp4', 'name': 'Ghost'},
        ])

        self.assertEqual(applied, 1)
        clip = next(c for c in self.store._list_clips_sync() if c.filename == 'demo.mp4')
        self.assertEqual(clip.name, 'Opening Loop')
        self.assertEqual(clip.folder, 'Show')
        self.assertTrue(clip.loop_enabled)
        self.assertEqual(clip.mark_in_seconds, 1.5)
        self.assertEqual(clip.mark_out_seconds, 9.0)
        self.assertEqual(clip.tags, 'intro, loop')


class ClipCacheTests(unittest.IsolatedAsyncioTestCase):
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
        self.store = ClipStore(self.config)
        self.store._initialize_sync()
        (Path(self.config.clips_dir) / 'demo.mp4').write_bytes(b'a')
        self.store._sync_with_disk_sync()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_list_clips_is_cached_between_reads(self) -> None:
        first = await self.store.list_clips()
        second = await self.store.list_clips()

        self.assertIs(first, second)

    async def test_writes_invalidate_the_cache(self) -> None:
        await self.store.list_clips()

        await self.store.set_tags(1, 'replay')

        clips = await self.store.list_clips()
        self.assertEqual(clips[0].tags, 'replay')

    async def test_get_clip_uses_cache_index(self) -> None:
        clip = await self.store.get_clip(1)

        self.assertIsNotNone(clip)
        self.assertEqual(clip.filename, 'demo.mp4')
        self.assertIsNone(await self.store.get_clip(99))

    async def test_processing_status_matches_cached_states(self) -> None:
        status = await self.store.processing_status()

        self.assertEqual(status['pending'], 1)
        self.assertEqual(status['ready'], 0)


class ConfigMigrationTests(unittest.TestCase):
    def test_legacy_video_only_extension_list_is_extended(self) -> None:
        from app.core.config import _migrate_upload_extensions

        migrated = _migrate_upload_extensions(['.mp4', '.mov', '.mkv'])

        self.assertIn('.png', migrated)
        self.assertIn('.jpg', migrated)
        self.assertIn('.mp4', migrated)

    def test_custom_extension_list_is_preserved_and_normalized(self) -> None:
        from app.core.config import _migrate_upload_extensions

        migrated = _migrate_upload_extensions(['MP4', '.MOV', ' webm '])

        self.assertEqual(migrated, ['.mp4', '.mov', '.webm'])

    def test_missing_list_falls_back_to_defaults(self) -> None:
        from app.core.config import _migrate_upload_extensions

        self.assertIn('.png', _migrate_upload_extensions(None))
        self.assertIn('.png', _migrate_upload_extensions([]))


class HelperFunctionTests(unittest.TestCase):
    def test_normalize_tags_dedupes_and_lowercases(self) -> None:
        self.assertEqual(normalize_tags('A; b,a , ,B'), 'a, b')
        self.assertEqual(normalize_tags(''), '')

    def test_parse_rms_levels_clamps_and_handles_silence(self) -> None:
        stdout = '\n'.join([
            'frame:0    pts:0       pts_time:0',
            'lavfi.astats.Overall.RMS_level=-23.456',
            'lavfi.astats.Overall.RMS_level=-inf',
            'lavfi.astats.Overall.RMS_level=3.2',
            'lavfi.astats.Overall.RMS_level=-90.0',
        ])

        self.assertEqual(parse_rms_levels(stdout), [-23.5, -60.0, 0.0, -60.0])

    def test_parse_rms_levels_caps_entry_count(self) -> None:
        stdout = '\n'.join(['lavfi.astats.Overall.RMS_level=-10.0'] * 50)

        self.assertEqual(len(parse_rms_levels(stdout, max_entries=20)), 20)


class RemoteClipTests(unittest.IsolatedAsyncioTestCase):
    """Add-link behavior: direct streams stay links, video pages (YouTube…)
    are downloaded via yt-dlp and become normal local clips."""

    PROBE_FALLBACK = {
        'duration_seconds': 0.0, 'duration_timecode': '00:00:00:00', 'framerate': 25.0,
        'codec': 'unknown', 'width': 0, 'height': 0, 'media_kind': 'video', 'is_vertical': False,
    }

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
        self.store = ClipStore(self.config)
        self.store._initialize_sync()
        # No network in tests: ffprobe "fails" (page URL) unless a test overrides.
        self.store._ffprobe_meta = lambda source, kind, timeout=None: dict(self.PROBE_FALLBACK)
        self.store._generate_remote_thumbnail = lambda url, key: None

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _settle(self) -> None:
        while self.store._remote_enrichment_tasks:
            await asyncio.gather(*list(self.store._remote_enrichment_tasks))

    @staticmethod
    def _fake_result(returncode: int, stdout: str = '', stderr: str = ''):
        return subprocess.CompletedProcess(args=['yt-dlp'], returncode=returncode, stdout=stdout, stderr=stderr)

    async def test_page_url_is_downloaded_and_becomes_local_clip(self) -> None:
        def fake_ytdlp(args, timeout):
            if '--dump-single-json' in args:
                return self._fake_result(0, stdout='{"title": "Big Buck Bunny", "duration": 596}')
            (Path(self.config.clips_dir) / 'Big Buck Bunny [aqz].mp4').write_bytes(b'fake video')
            return self._fake_result(0)

        self.store._run_ytdlp = fake_ytdlp
        await self.store.add_remote_clip('https://www.youtube.com/watch?v=aqz')
        await self._settle()

        clips = await self.store.list_clips()
        self.assertEqual([c.filename for c in clips if c.is_remote], [])
        self.assertIn('Big Buck Bunny [aqz].mp4', [c.filename for c in clips])

    async def test_failed_probe_marks_link_in_error(self) -> None:
        self.store._run_ytdlp = lambda args, timeout: self._fake_result(1, stderr='ERROR: Unsupported URL')
        await self.store.add_remote_clip('https://example.com/not-a-video')
        await self._settle()

        clip = (await self.store.list_clips())[0]
        self.assertEqual(clip.processing_state, 'error')
        self.assertIn('Unsupported URL', clip.error_reason)

    async def test_direct_stream_stays_a_link_without_ytdlp(self) -> None:
        meta = dict(self.PROBE_FALLBACK, codec='h264', width=1920, height=1080, duration_seconds=42.0)
        self.store._ffprobe_meta = lambda source, kind, timeout=None: meta
        self.store._run_ytdlp = lambda args, timeout: self.fail('yt-dlp must not run for a direct stream')
        await self.store.add_remote_clip('https://example.com/stream.m3u8')
        await self._settle()

        clip = (await self.store.list_clips())[0]
        self.assertTrue(clip.is_remote)
        self.assertEqual(clip.codec, 'h264')

    async def test_live_page_stays_a_streaming_link(self) -> None:
        def fake_ytdlp(args, timeout):
            if '--dump-single-json' in args:
                return self._fake_result(0, stdout='{"title": "My Twitch Live", "is_live": true}')
            return self.fail('a live stream must never be downloaded')

        self.store._run_ytdlp = fake_ytdlp
        await self.store.add_remote_clip('https://www.twitch.tv/somestreamer')
        await self._settle()

        clip = (await self.store.list_clips())[0]
        self.assertTrue(clip.is_remote)
        self.assertEqual(clip.processing_state, 'ready')
        self.assertEqual(clip.name, 'My Twitch Live')

    async def test_disconnected_destination_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await self.store.add_remote_clip('https://example.com/x.mp4', destination='/media/ghost/usb')

    async def test_resolution_cap_is_stored_and_caps_the_download(self) -> None:
        captured: list[list[str]] = []

        def fake_ytdlp(args, timeout):
            captured.append(list(args))
            if '--dump-single-json' in args:
                return self._fake_result(0, stdout='{"title": "Concert", "is_live": true}')
            return self._fake_result(0)

        self.store._run_ytdlp = fake_ytdlp
        await self.store.add_remote_clip('https://www.twitch.tv/somestreamer', max_height=1080)
        await self._settle()
        clip = (await self.store.list_clips())[0]
        self.assertEqual(clip.remote_max_height, 1080)

        with self.assertRaises(ValueError):
            await self.store.add_remote_clip('https://example.com/y', max_height=333)

        # A VOD download passes the cap to yt-dlp's format sort.
        def fake_vod(args, timeout):
            if '--dump-single-json' in args:
                return self._fake_result(0, stdout='{"title": "Rediff", "duration": 60}')
            self.assertIn('res:480,vcodec:h264,acodec:m4a', args)
            (Path(self.config.clips_dir) / 'Rediff [x].mp4').write_bytes(b'v')
            return self._fake_result(0)

        self.store._run_ytdlp = fake_vod
        await self.store.add_remote_clip('https://www.youtube.com/watch?v=x', max_height=480)
        await self._settle()
        self.assertIn('Rediff [x].mp4', [c.filename for c in await self.store.list_clips()])


if __name__ == '__main__':
    unittest.main()
