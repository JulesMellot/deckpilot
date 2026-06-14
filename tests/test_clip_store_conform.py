from __future__ import annotations

import unittest
from pathlib import Path

from app.core.config import AppConfig
from app.media.clip_store import ClipStore


def _store(**overrides) -> ClipStore:
    return ClipStore(AppConfig(**overrides))


class ConformTargetTests(unittest.TestCase):
    def test_target_parsed_from_video_format(self) -> None:
        self.assertEqual(_store(default_video_format='1080p25')._conform_target(), (1920, 1080))
        self.assertEqual(_store(default_video_format='720p50')._conform_target(), (1280, 720))

    def test_target_defaults_to_1080_when_unparseable(self) -> None:
        self.assertEqual(_store(default_video_format='')._conform_target(), (1920, 1080))


class ConformNeededTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store(conform_clips=True, default_video_format='1080p25')

    def _video(self, codec: str, width: int, height: int) -> dict:
        return {'media_kind': 'video', 'codec': codec, 'width': width, 'height': height}

    def test_disabled_never_conforms(self) -> None:
        store = _store(conform_clips=False, default_video_format='1080p25')
        self.assertFalse(store._conform_needed(self._video('h264', 640, 480)))

    def test_h264_at_target_passes_through(self) -> None:
        self.assertFalse(self.store._conform_needed(self._video('h264', 1920, 1080)))

    def test_smaller_resolution_needs_conform(self) -> None:
        self.assertTrue(self.store._conform_needed(self._video('h264', 1280, 720)))

    def test_wrong_codec_at_target_needs_conform(self) -> None:
        # 1080p HEVC would software-decode and stutter, so it must be re-encoded.
        self.assertTrue(self.store._conform_needed(self._video('hevc', 1920, 1080)))

    def test_images_are_never_conformed(self) -> None:
        self.assertFalse(self.store._conform_needed({'media_kind': 'image', 'codec': 'png', 'width': 800, 'height': 600}))


class ConformCommandTests(unittest.TestCase):
    def test_command_scales_pads_and_forces_mp4(self) -> None:
        store = _store(conform_clips=True, default_video_format='1080p25')
        cmd = store._conform_command(Path('/clips/in.mov'), Path('/clips/in.mov.conforming'), 'h264_v4l2m2m')

        joined = ' '.join(cmd)
        self.assertIn('scale=1920:1080:force_original_aspect_ratio=decrease', joined)
        self.assertIn('pad=1920:1080', joined)
        self.assertIn('h264_v4l2m2m', cmd)
        self.assertIn('mp4', cmd)  # -f mp4 regardless of the .mov extension
        self.assertEqual(cmd[-1], '/clips/in.mov.conforming')


if __name__ == '__main__':
    unittest.main()
