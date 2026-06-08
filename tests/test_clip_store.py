from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from app.core.config import AppConfig
from app.media.clip_store import ClipStore


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
        self.assertEqual(clips[0].processing_state, 'pending')

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


if __name__ == '__main__':
    unittest.main()
