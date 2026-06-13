from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any, Awaitable, Callable, Iterable, List
from urllib.parse import urlparse

from app.core.config import AppConfig
from app.core.models import ClipRecord
from app.services.storage_devices import removable_media_roots

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
# URL schemes mpv can open directly via loadfile. Anything else (a bare path,
# file://, javascript:, ...) is rejected when adding a network clip.
REMOTE_URL_SCHEMES = {
    'http', 'https', 'rtsp', 'rtsps', 'rtmp', 'rtmps', 'rtp', 'udp', 'srt',
    'mms', 'mmsh', 'hls', 'ftp', 'ftps', 'tcp',
}


def _path_under(root: str, path: str) -> bool:
    """True if ``path`` lives inside (or is) the directory ``root``."""
    root = os.path.normpath(root)
    path = os.path.normpath(path)
    return path == root or path.startswith(root + os.sep)


class ClipStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db_path = Path(config.db_path)
        self.clips_dir = Path(config.clips_dir)
        self.thumbnails_dir = Path(config.thumbnails_dir)
        self._enrichment_queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued_enrichment: set[str] = set()
        self._enrichment_workers: list[asyncio.Task] = []
        self._enrichment_worker_count = max(1, int(config.media_enrichment_workers or 1))
        self._enrichment_notify_task: asyncio.Task | None = None
        self._enrichment_notify_event = asyncio.Event()
        self._remote_enrichment_tasks: set[asyncio.Task] = set()
        self._enrichment_callback: Callable[[], Awaitable[None]] | None = None
        self._processing_metrics_lock = Lock()
        self._processing_batch_started_at: float | None = None
        self._processing_batch_total = 0
        self._processing_batch_completed = 0
        # Hot-path cache: the clip list is read every transport tick and every
        # health report, so it lives in memory and is invalidated on writes.
        self._clips_cache: list[ClipRecord] | None = None
        self._clips_index: dict[int, ClipRecord] = {}
        self._clips_cache_generation = 0

    def _invalidate_clips_cache(self) -> None:
        self._clips_cache_generation += 1
        self._clips_cache = None
        self._clips_index = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)
        await self.ensure_builtin_clips()

    async def start_background_tasks(self, on_enriched: Callable[[], Awaitable[None]] | None = None) -> None:
        self._enrichment_callback = on_enriched
        if not self._enrichment_workers or any(worker.done() for worker in self._enrichment_workers):
            self._enrichment_workers = [
                asyncio.create_task(self._enrichment_worker(index))
                for index in range(self._enrichment_worker_count)
            ]
        if on_enriched and (self._enrichment_notify_task is None or self._enrichment_notify_task.done()):
            self._enrichment_notify_task = asyncio.create_task(self._enrichment_notifier())

    async def stop_background_tasks(self) -> None:
        tasks = [*self._enrichment_workers]
        if self._enrichment_notify_task:
            tasks.append(self._enrichment_notify_task)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._enrichment_workers = []
        self._enrichment_notify_task = None
        self._enrichment_callback = None
        self._enrichment_notify_event.clear()
        self._queued_enrichment.clear()
        self._enrichment_queue = asyncio.Queue()
        with self._processing_metrics_lock:
            self._processing_batch_started_at = None
            self._processing_batch_total = 0
            self._processing_batch_completed = 0

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # WAL + NORMAL: far fewer fsyncs per write — important on SD cards.
        conn.execute('PRAGMA busy_timeout = 5000')
        conn.execute('PRAGMA synchronous = NORMAL')
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    folder TEXT NOT NULL DEFAULT 'Library',
                    filename TEXT NOT NULL UNIQUE,
                    filepath TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    duration_timecode TEXT NOT NULL DEFAULT '00:00:00:00',
                    framerate REAL NOT NULL DEFAULT 25.0,
                    codec TEXT NOT NULL DEFAULT 'unknown',
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    media_kind TEXT NOT NULL DEFAULT 'video',
                    is_vertical INTEGER NOT NULL DEFAULT 0,
                    thumbnail_path TEXT,
                    processing_state TEXT NOT NULL DEFAULT 'ready',
                    loop_enabled INTEGER NOT NULL DEFAULT 0,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    is_remote INTEGER NOT NULL DEFAULT 0,
                    mark_in_seconds REAL NOT NULL DEFAULT 0,
                    mark_out_seconds REAL NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pad_assignments (
                    pad INTEGER PRIMARY KEY CHECK (pad BETWEEN 1 AND 9),
                    filename TEXT NOT NULL
                )
                """
            )
            columns = [row[1] for row in conn.execute("PRAGMA table_info(clips)").fetchall()]
            if 'folder' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN folder TEXT NOT NULL DEFAULT 'Library'")
            if 'width' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN width INTEGER NOT NULL DEFAULT 0")
            if 'height' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN height INTEGER NOT NULL DEFAULT 0")
            if 'media_kind' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN media_kind TEXT NOT NULL DEFAULT 'video'")
            if 'is_vertical' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN is_vertical INTEGER NOT NULL DEFAULT 0")
            if 'processing_state' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN processing_state TEXT NOT NULL DEFAULT 'ready'")
            if 'mark_in_seconds' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN mark_in_seconds REAL NOT NULL DEFAULT 0")
            if 'mark_out_seconds' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN mark_out_seconds REAL NOT NULL DEFAULT 0")
            if 'tags' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
            if 'audio_levels' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN audio_levels TEXT")
            if 'is_remote' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN is_remote INTEGER NOT NULL DEFAULT 0")
            conn.execute("INSERT OR IGNORE INTO media_folders (name) VALUES ('Library')")
            conn.execute("INSERT OR IGNORE INTO media_folders (name) VALUES ('System')")
            conn.commit()
        self._invalidate_clips_cache()

    def _source_roots(self) -> list[str]:
        """Disks scanned for clips: the internal library plus any USB drives.

        The internal directory is always first so that, when the same filename
        exists on two disks, the internal copy wins the unique-filename slot.
        """
        roots = [str(self.clips_dir)]
        for mount in removable_media_roots():
            if mount not in roots:
                roots.append(mount)
        return roots

    def _scan_source_files(self, roots: list[str]) -> tuple[list[Path], list[str]]:
        """Return (media files, roots that were successfully read).

        A root missing from the second list was unreadable this pass (vanished
        or browned-out drive); its existing clips must not be treated as deleted.
        """
        allowed = set(self.config.allowed_upload_extensions)
        files: list[Path] = []
        seen_names: set[str] = set()
        scanned_roots: list[str] = []
        for root in roots:
            try:
                entries = sorted(Path(root).iterdir())
            except OSError:
                # An unreadable / vanished mount must never abort the scan, and
                # is deliberately left out of scanned_roots.
                continue
            scanned_roots.append(root)
            for path in entries:
                # Skip dotfiles, incl. macOS AppleDouble sidecars (._*) and
                # .DS_Store that ride along on USB / SMB copies.
                if path.name.startswith('.'):
                    continue
                if not path.is_file() or path.suffix.lower() not in allowed:
                    continue
                # Filename is the library's unique key; the first disk to carry
                # a given name wins, later duplicates on other disks are skipped.
                if path.name in seen_names:
                    continue
                seen_names.add(path.name)
                files.append(path)
        return files, scanned_roots

    async def sync_with_disk(self) -> None:
        pending_paths = await asyncio.to_thread(self._sync_with_disk_sync)
        await self._enqueue_enrichment_paths(pending_paths)

    def _sync_with_disk_sync(self) -> list[str]:
        roots = self._source_roots()
        files, scanned_roots = self._scan_source_files(roots)
        pending_paths: list[str] = []
        with self._connect() as conn:
            existing = {row['filename']: row for row in conn.execute('SELECT * FROM clips').fetchall()}
            sort_seed = conn.execute('SELECT COALESCE(MAX(sort_order), 0) FROM clips').fetchone()[0]

            for file_path in files:
                if file_path.name in existing:
                    row = existing[file_path.name]
                    moved = os.path.normpath(row['filepath']) != os.path.normpath(str(file_path))
                    needs_meta_refresh = self._metadata_needs_refresh(row)
                    needs_thumb_refresh = self._thumbnail_needs_refresh(file_path, row['thumbnail_path'])
                    if moved:
                        # The file now lives on a different disk (e.g. the clip
                        # was copied to a USB drive): re-point and re-probe it.
                        conn.execute(
                            'UPDATE clips SET filepath = ?, processing_state = ? WHERE filename = ?',
                            (str(file_path), 'pending', file_path.name),
                        )
                        pending_paths.append(str(file_path))
                    elif needs_meta_refresh or needs_thumb_refresh:
                        conn.execute(
                            'UPDATE clips SET processing_state = ? WHERE filename = ?',
                            ('pending', file_path.name),
                        )
                        pending_paths.append(str(file_path))
                    continue
                sort_seed += 1
                conn.execute(
                    """
                    INSERT INTO clips (
                        sort_order, name, folder, filename, filepath, duration_seconds, duration_timecode,
                        framerate, codec, width, height, media_kind, is_vertical, thumbnail_path, processing_state, loop_enabled, is_builtin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                    """,
                    (
                        sort_seed,
                        file_path.stem,
                        'Library',
                        file_path.name,
                        str(file_path),
                        0.0,
                        '00:00:00:00',
                        self.config.default_framerate,
                        'unknown',
                        0,
                        0,
                        self._media_kind_for_path(file_path),
                        0,
                        None,
                        'pending',
                    ),
                )
                pending_paths.append(str(file_path))

            # Delete only files that vanished from a disk we actually read this
            # pass. Clips on an unplugged drive — or one that browned out and
            # failed to scan — are kept (shown offline) so their names, marks,
            # folders and playlist references survive until the drive returns.
            disk_paths = {os.path.normpath(str(item)) for item in files}
            for row in conn.execute('SELECT filename, filepath, thumbnail_path FROM clips WHERE is_builtin = 0 AND is_remote = 0').fetchall():
                root_scanned = any(_path_under(root, row['filepath']) for root in scanned_roots)
                if root_scanned and os.path.normpath(row['filepath']) not in disk_paths:
                    if row['thumbnail_path']:
                        Path(row['thumbnail_path']).unlink(missing_ok=True)
                    conn.execute('DELETE FROM clips WHERE filename = ?', (row['filename'],))
            conn.commit()
        self._invalidate_clips_cache()
        return pending_paths

    async def ensure_builtin_clips(self) -> None:
        await asyncio.to_thread(self._ensure_builtin_clips_sync)

    def _ensure_builtin_clips_sync(self) -> None:
        if not shutil.which(self.config.ffmpeg_binary):
            return
        builtins = [
            ('_builtin_black.mp4', 'Black', f"color=c=black:s=1920x1080:r={int(self.config.default_framerate)}", None),
            (
                '_builtin_test_pattern.mp4',
                'Test Pattern',
                f"smptebars=size=1920x1080:rate={int(self.config.default_framerate)}",
                'sine=frequency=1000:sample_rate=48000',
            ),
        ]
        with self._connect() as conn:
            sort_seed = conn.execute('SELECT COALESCE(MAX(sort_order), 0) FROM clips').fetchone()[0]
            for filename, display_name, video_filter, audio_filter in builtins:
                output = self.clips_dir / filename
                if not output.exists():
                    cmd = [self.config.ffmpeg_binary, '-y', '-f', 'lavfi', '-i', video_filter]
                    if audio_filter:
                        cmd.extend(['-f', 'lavfi', '-i', audio_filter])
                    cmd.extend(['-t', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p'])
                    if audio_filter:
                        cmd.extend(['-c:a', 'aac'])
                    else:
                        cmd.extend(['-an'])
                    cmd.append(str(output))
                    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                row = conn.execute('SELECT 1 FROM clips WHERE filename = ?', (filename,)).fetchone()
                if row or not output.exists():
                    continue
                sort_seed += 1
                meta = self._probe_clip(output)
                thumb = self._generate_thumbnail(output)
                conn.execute(
                    """
                    INSERT INTO clips (
                        sort_order, name, folder, filename, filepath, duration_seconds, duration_timecode,
                        framerate, codec, width, height, media_kind, is_vertical, thumbnail_path, processing_state, loop_enabled, is_builtin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                    """,
                    (
                        sort_seed,
                        display_name,
                        'System',
                        filename,
                        str(output),
                        meta['duration_seconds'],
                        meta['duration_timecode'],
                        meta['framerate'],
                        meta['codec'],
                        meta['width'],
                        meta['height'],
                        meta['media_kind'],
                        1 if meta['is_vertical'] else 0,
                        thumb,
                        'ready',
                    ),
                )
            conn.commit()
        self._invalidate_clips_cache()

    def _probe_clip(self, file_path: Path) -> dict:
        return self._ffprobe_meta(str(file_path), self._media_kind_for_path(file_path))

    def _ffprobe_meta(self, source: str, media_kind: str, timeout: float | None = None) -> dict:
        """Probe a local path or a network URL (``source`` is passed verbatim)."""
        if not shutil.which(self.config.ffprobe_binary):
            return {
                'duration_seconds': self._default_duration_for_kind(media_kind),
                'duration_timecode': seconds_to_timecode(self._default_duration_for_kind(media_kind), self.config.default_framerate),
                'framerate': self.config.default_framerate,
                'codec': media_kind if media_kind == 'image' else 'unknown',
                'width': 0,
                'height': 0,
                'media_kind': media_kind,
                'is_vertical': False,
            }
        cmd = [
            self.config.ffprobe_binary,
            '-v',
            'error',
            '-show_entries',
            'stream=codec_name,r_frame_rate,width,height:format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=0',
            source,
        ]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            # A slow / unreachable stream falls back to an open-ended source.
            return {
                'duration_seconds': 0.0,
                'duration_timecode': '00:00:00:00',
                'framerate': self.config.default_framerate,
                'codec': 'unknown',
                'width': 0,
                'height': 0,
                'media_kind': media_kind,
                'is_vertical': False,
            }
        duration_seconds = 0.0
        framerate = self.config.default_framerate
        codec = 'unknown'
        width = 0
        height = 0
        for line in result.stdout.splitlines():
            if line.startswith('duration='):
                raw_duration = line.split('=', 1)[1]
                try:
                    duration_seconds = float(raw_duration or 0)
                except ValueError:
                    duration_seconds = 0.0
            elif line.startswith('r_frame_rate='):
                raw = line.split('=', 1)[1]
                if '/' in raw:
                    num, den = raw.split('/', 1)
                    if float(den or 1) != 0:
                        value = round(float(num) / float(den), 2)
                        if value > 0:
                            framerate = value
            elif line.startswith('codec_name=') and codec == 'unknown':
                codec = line.split('=', 1)[1]
            elif line.startswith('width=') and width == 0:
                width = int(float(line.split('=', 1)[1] or 0))
            elif line.startswith('height=') and height == 0:
                height = int(float(line.split('=', 1)[1] or 0))
        if media_kind == 'image' and duration_seconds <= 0:
            duration_seconds = self.config.default_image_duration_seconds
        return {
            'duration_seconds': duration_seconds,
            'duration_timecode': seconds_to_timecode(duration_seconds, framerate),
            'framerate': framerate,
            'codec': codec,
            'width': width,
            'height': height,
            'media_kind': media_kind,
            'is_vertical': bool(height and width and height > width),
        }

    def _metadata_needs_refresh(self, row: sqlite3.Row) -> bool:
        expected_kind = self._media_kind_for_path(Path(row['filepath']))
        return (
            not row['media_kind']
            or row['media_kind'] != expected_kind
            or not row['width']
            or not row['height']
            or not row['duration_seconds']
            or row['duration_timecode'] == '00:00:00:00'
            or row['codec'] == 'unknown'
            or not row['framerate']
            or (expected_kind == 'video' and row['audio_levels'] is None)
        )

    def _generate_thumbnail(self, file_path: Path) -> str | None:
        if not shutil.which(self.config.ffmpeg_binary):
            return None
        output = self._thumbnail_output_path(file_path)
        is_video = self._media_kind_for_path(file_path) == 'video'
        # Seek-before-input decodes a single GOP instead of the ~100 frames the
        # `thumbnail` filter walks through — an order of magnitude faster on a Pi.
        self._run_thumbnail_command(file_path, output, seek_seconds=1.0 if is_video else None)
        if not output.exists() and is_video:
            # Clips shorter than the seek point: grab the first frame instead.
            self._run_thumbnail_command(file_path, output, seek_seconds=None)
        return str(output) if output.exists() else None

    def _run_thumbnail_command(self, file_path: Path, output: Path, seek_seconds: float | None) -> None:
        cmd = [self.config.ffmpeg_binary, '-y', '-hide_banner', '-loglevel', 'error']
        if seek_seconds is not None:
            cmd.extend(['-ss', str(seek_seconds)])
        cmd.extend([
            '-i',
            str(file_path),
            '-frames:v',
            '1',
            '-vf',
            'scale=256:-2:flags=lanczos',
            '-q:v',
            '6',
            '-map_metadata',
            '-1',
            str(output),
        ])
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)

    def _thumbnail_output_path(self, file_path: Path) -> Path:
        stats = file_path.stat()
        fingerprint = hashlib.sha1(
            f'{file_path.name}:{stats.st_mtime_ns}:{stats.st_size}'.encode('utf-8')
        ).hexdigest()[:16]
        return self.thumbnails_dir / f'{file_path.stem}-{fingerprint}.jpg'

    def _thumbnail_needs_refresh(self, file_path: Path, thumbnail_path: str | None) -> bool:
        if not thumbnail_path:
            return True
        output = Path(thumbnail_path)
        expected_output = self._thumbnail_output_path(file_path)
        if output != expected_output:
            return True
        if not output.exists():
            return True
        try:
            return output.stat().st_mtime_ns < file_path.stat().st_mtime_ns
        except FileNotFoundError:
            return True

    async def _enqueue_enrichment_paths(self, paths: Iterable[str]) -> None:
        queued_count = 0
        for path in paths:
            if path in self._queued_enrichment:
                continue
            self._queued_enrichment.add(path)
            await self._enrichment_queue.put(path)
            queued_count += 1
        if queued_count:
            self._record_batch_enqueue(queued_count)

    async def _enrichment_worker(self, _worker_index: int) -> None:
        while True:
            path = await self._enrichment_queue.get()
            try:
                filename = Path(path).name
                await asyncio.to_thread(self._set_processing_state_sync, filename, 'processing')
                changed = await asyncio.to_thread(self._enrich_clip_sync, Path(path))
                if changed:
                    self._enrichment_notify_event.set()
                else:
                    await asyncio.to_thread(self._set_processing_state_sync, filename, 'error')
                    self._enrichment_notify_event.set()
                self._record_batch_completion()
            except Exception:
                await asyncio.to_thread(self._set_processing_state_sync, Path(path).name, 'error')
                self._enrichment_notify_event.set()
                self._record_batch_completion()
            finally:
                self._queued_enrichment.discard(path)
                self._enrichment_queue.task_done()

    async def _enrichment_notifier(self) -> None:
        while True:
            await self._enrichment_notify_event.wait()
            self._enrichment_notify_event.clear()
            await asyncio.sleep(0.25)
            if self._enrichment_notify_event.is_set():
                continue
            if self._enrichment_callback:
                await self._enrichment_callback()

    def _enrich_clip_sync(self, file_path: Path) -> bool:
        if not file_path.exists():
            return False
        meta = self._probe_clip(file_path)
        media_kind = meta.get('media_kind', self._media_kind_for_path(file_path))
        thumb = self._generate_thumbnail(file_path)
        audio_levels = self._compute_audio_levels(file_path) if media_kind == 'video' else []
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM clips WHERE filename = ?', (file_path.name,)).fetchone()
            if not row:
                return False
            old_thumb = row['thumbnail_path']
            duration_seconds = meta['duration_seconds']
            duration_timecode = meta['duration_timecode']
            if media_kind == 'image' and float(row['duration_seconds'] or 0.0) > 0:
                # Stills keep their operator-set duration across re-enrichment.
                duration_seconds = float(row['duration_seconds'])
                duration_timecode = seconds_to_timecode(duration_seconds, meta['framerate'])
            conn.execute(
                '''
                UPDATE clips
                SET width = ?, height = ?, media_kind = ?, is_vertical = ?, codec = ?, framerate = ?, duration_seconds = ?, duration_timecode = ?, thumbnail_path = ?, audio_levels = ?, processing_state = ?
                WHERE filename = ?
                ''',
                (
                    meta['width'],
                    meta['height'],
                    media_kind,
                    1 if meta['is_vertical'] else 0,
                    meta['codec'],
                    meta['framerate'],
                    duration_seconds,
                    duration_timecode,
                    thumb,
                    json.dumps(audio_levels),
                    'ready',
                    file_path.name,
                ),
            )
            conn.commit()
        self._invalidate_clips_cache()
        if old_thumb and old_thumb != thumb:
            Path(old_thumb).unlink(missing_ok=True)
        return True

    def _compute_audio_levels(self, file_path: Path) -> list[float]:
        """Per-second RMS envelope (dBFS, clamped to [-60, 0]) precomputed once at
        import time so the UI VU meter costs nothing during playback."""
        if not shutil.which(self.config.ffmpeg_binary):
            return []
        cmd = [
            self.config.ffmpeg_binary,
            '-hide_banner',
            '-nostats',
            '-v',
            'error',
            '-i',
            str(file_path),
            '-vn',
            '-af',
            'aresample=8000,asetnsamples=n=8000,astats=metadata=1:reset=1,'
            'ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-',
            '-f',
            'null',
            '-',
        ]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return []
        return parse_rms_levels(result.stdout)

    def _set_processing_state_sync(self, filename: str, state: str) -> None:
        with self._connect() as conn:
            conn.execute('UPDATE clips SET processing_state = ? WHERE filename = ?', (state, filename))
            conn.commit()
        self._invalidate_clips_cache()

    def _record_batch_enqueue(self, count: int) -> None:
        with self._processing_metrics_lock:
            if (
                self._processing_batch_started_at is None
                or self._processing_batch_completed >= self._processing_batch_total
            ):
                self._processing_batch_started_at = time.monotonic()
                self._processing_batch_total = 0
                self._processing_batch_completed = 0
            self._processing_batch_total += count

    def _record_batch_completion(self) -> None:
        with self._processing_metrics_lock:
            if self._processing_batch_started_at is None:
                self._processing_batch_started_at = time.monotonic()
            self._processing_batch_completed += 1
            if self._processing_batch_completed > self._processing_batch_total:
                self._processing_batch_total = self._processing_batch_completed

    async def processing_status(self) -> dict[str, int]:
        # Derived from the in-memory clip cache: called every health tick, so it
        # must not touch SQLite.
        clips = await self.list_clips()
        counts: dict[str, int] = {}
        for clip in clips:
            state = clip.processing_state or 'ready'
            counts[state] = counts.get(state, 0) + 1
        return self._processing_status_from_counts(counts)

    def _processing_status_sync(self) -> dict[str, int | float | None]:
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT processing_state, COUNT(*) AS count
                FROM clips
                GROUP BY processing_state
                '''
            ).fetchall()
        counts = {row['processing_state']: row['count'] for row in rows}
        return self._processing_status_from_counts(counts)

    def _processing_status_from_counts(self, counts: dict[str, int]) -> dict[str, int | float | None]:
        pending = int(counts.get('pending', 0))
        processing = int(counts.get('processing', 0))
        error = int(counts.get('error', 0))
        ready = int(counts.get('ready', 0))
        remaining = pending + processing
        clips_per_second: float | None = None
        eta_seconds: float | None = None
        with self._processing_metrics_lock:
            started_at = self._processing_batch_started_at
            batch_total = self._processing_batch_total
            batch_completed = self._processing_batch_completed
        if remaining > 0 and started_at is not None and batch_completed > 0:
            elapsed = max(time.monotonic() - started_at, 0.001)
            effective_completed = max(batch_completed, batch_total - remaining)
            if effective_completed > 0:
                clips_per_second = round(effective_completed / elapsed, 2)
                if clips_per_second > 0:
                    eta_seconds = round(remaining / clips_per_second, 1)
        return {
            'pending': pending,
            'processing': processing,
            'error': error,
            'ready': ready,
            'queued': self._enrichment_queue.qsize(),
            'clips_per_second': clips_per_second,
            'eta_seconds': eta_seconds,
        }

    async def save_upload_streams(self, uploads: Iterable[Any]) -> None:
        for upload in uploads:
            filename = Path(getattr(upload, 'filename', '') or 'clip.bin').name
            destination = self.clips_dir / filename
            await asyncio.to_thread(self._save_upload_stream_sync, upload, destination)

    def _save_upload_stream_sync(self, upload: Any, destination: Path) -> None:
        fileobj = upload.file
        fileobj.seek(0)
        with destination.open('wb') as handle:
            shutil.copyfileobj(fileobj, handle, length=1024 * 1024)

    async def save_uploads(self, uploads: Iterable[tuple[str, bytes]]) -> None:
        for filename, content in uploads:
            destination = self.clips_dir / Path(filename).name
            destination.write_bytes(content)

    async def list_clips(self) -> List[ClipRecord]:
        cached = self._clips_cache
        if cached is not None:
            return cached
        generation = self._clips_cache_generation
        clips = await asyncio.to_thread(self._list_clips_sync)
        # Only cache if no write landed while the read was in flight.
        if generation == self._clips_cache_generation:
            self._clips_index = {clip.deck_id: clip for clip in clips}
            self._clips_cache = clips
        return clips

    def _source_label_resolver(self) -> Callable[[str, bool], tuple[str, bool]]:
        """Build a cheap (filepath, is_builtin) -> (source, available) classifier.

        Reads the connected drives once so the per-clip listing stays in pure
        string space (no filesystem stat on the hot path).
        """
        internal_root = os.path.normpath(str(self.clips_dir))
        connected = {os.path.normpath(mount): Path(mount).name for mount in removable_media_roots()}

        def classify(filepath: str, is_builtin: bool) -> tuple[str, bool]:
            if is_builtin or _path_under(internal_root, filepath):
                return 'Internal', True
            for mount, label in connected.items():
                if _path_under(mount, filepath):
                    return label or 'USB', True
            return 'USB', False  # the drive holding this clip is unplugged

        return classify

    def _list_clips_sync(self) -> List[ClipRecord]:
        classify = self._source_label_resolver()
        with self._connect() as conn:
            # audio_levels can be tens of KB per clip; only its presence is listed.
            rows = conn.execute(
                '''
                SELECT id, sort_order, name, folder, filename, filepath, duration_seconds,
                       duration_timecode, framerate, codec, width, height, media_kind,
                       is_vertical, thumbnail_path, processing_state, loop_enabled, is_builtin, is_remote,
                       mark_in_seconds, mark_out_seconds, tags,
                       (CASE WHEN audio_levels IS NOT NULL AND LENGTH(audio_levels) > 2 THEN 1 ELSE 0 END) AS has_audio_levels
                FROM clips ORDER BY sort_order ASC, id ASC
                '''
            ).fetchall()
        clips: list[ClipRecord] = []
        for index, row in enumerate(rows, start=1):
            is_remote = bool(row['is_remote'])
            if is_remote:
                source, available = 'Link', True
            else:
                source, available = classify(row['filepath'], bool(row['is_builtin']))
            clips.append(
                ClipRecord(
                    deck_id=index,
                    name=row['name'],
                    folder=row['folder'],
                    filepath=row['filepath'],
                    filename=row['filename'],
                    duration_seconds=row['duration_seconds'],
                    duration_timecode=row['duration_timecode'],
                    framerate=row['framerate'],
                    codec=row['codec'],
                    width=row['width'],
                    height=row['height'],
                    media_kind=row['media_kind'] or self._media_kind_for_path(Path(row['filepath'])),
                    is_vertical=bool(row['is_vertical']),
                    thumbnail_path=row['thumbnail_path'],
                    processing_state=row['processing_state'] or 'ready',
                    loop_enabled=bool(row['loop_enabled']),
                    is_builtin=bool(row['is_builtin']),
                    mark_in_seconds=float(row['mark_in_seconds'] or 0.0),
                    mark_out_seconds=float(row['mark_out_seconds'] or 0.0),
                    tags=row['tags'] or '',
                    has_audio_levels=bool(row['has_audio_levels']),
                    source=source,
                    available=available,
                    is_remote=is_remote,
                )
            )
        return clips

    async def path_for_filename(self, filename: str) -> str | None:
        return await asyncio.to_thread(self._path_for_filename_sync, filename)

    def _path_for_filename_sync(self, filename: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute('SELECT filepath FROM clips WHERE filename = ? AND is_remote = 0', (filename,)).fetchone()
        return row['filepath'] if row else None

    async def add_remote_clip(self, url: str, name: str | None = None) -> str:
        """Add a network link (http/rtsp/...) as a playable clip.

        Inserts immediately so the operator sees it, then probes the URL in the
        background for duration / thumbnail; a slow or live source just stays an
        open-ended clip.
        """
        key, clean_url = await asyncio.to_thread(self._insert_remote_clip_sync, url, name)
        task = asyncio.create_task(self._enrich_remote_clip(key, clean_url))
        self._remote_enrichment_tasks.add(task)
        task.add_done_callback(self._remote_enrichment_tasks.discard)
        return key

    def _insert_remote_clip_sync(self, url: str, name: str | None) -> tuple[str, str]:
        clean = (url or '').strip()
        parsed = urlparse(clean)
        if parsed.scheme.lower() not in REMOTE_URL_SCHEMES or not parsed.netloc:
            raise ValueError('Enter a full media URL, e.g. https://… or rtsp://…')
        key = 'link-' + hashlib.sha1(clean.encode('utf-8')).hexdigest()[:16]
        display = (name or '').strip() or self._remote_display_name(parsed)
        with self._connect() as conn:
            duplicate = conn.execute(
                'SELECT 1 FROM clips WHERE filepath = ? OR filename = ?', (clean, key)
            ).fetchone()
            if duplicate:
                raise ValueError('That link is already in the library.')
            sort_seed = conn.execute('SELECT COALESCE(MAX(sort_order), 0) FROM clips').fetchone()[0]
            conn.execute(
                """
                INSERT INTO clips (
                    sort_order, name, folder, filename, filepath, duration_seconds, duration_timecode,
                    framerate, codec, width, height, media_kind, is_vertical, thumbnail_path, processing_state, loop_enabled, is_builtin, is_remote
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1)
                """,
                (
                    sort_seed + 1,
                    display,
                    'Library',
                    key,
                    clean,
                    0.0,
                    '00:00:00:00',
                    self.config.default_framerate,
                    'unknown',
                    0,
                    0,
                    'video',
                    0,
                    None,
                    'pending',
                ),
            )
            conn.commit()
        self._invalidate_clips_cache()
        return key, clean

    @staticmethod
    def _remote_display_name(parsed) -> str:
        tail = parsed.path.rstrip('/').rsplit('/', 1)[-1]
        return tail or parsed.netloc or 'Network link'

    async def _enrich_remote_clip(self, filename: str, url: str) -> None:
        try:
            await asyncio.to_thread(self._set_processing_state_sync, filename, 'processing')
            self._enrichment_notify_event.set()
            meta = await asyncio.to_thread(self._ffprobe_meta, url, 'video', 20.0)
            thumb = await asyncio.to_thread(self._generate_remote_thumbnail, url, filename)
            await asyncio.to_thread(self._apply_remote_meta_sync, filename, meta, thumb)
        except Exception:
            # Never let a bad link wedge the clip in 'processing'.
            await asyncio.to_thread(self._set_processing_state_sync, filename, 'ready')
        finally:
            self._enrichment_notify_event.set()

    def _apply_remote_meta_sync(self, filename: str, meta: dict, thumb: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                UPDATE clips
                SET width = ?, height = ?, is_vertical = ?, codec = ?, framerate = ?,
                    duration_seconds = ?, duration_timecode = ?, thumbnail_path = ?, processing_state = 'ready'
                WHERE filename = ?
                ''',
                (
                    meta['width'],
                    meta['height'],
                    1 if meta['is_vertical'] else 0,
                    meta['codec'],
                    meta['framerate'],
                    meta['duration_seconds'],
                    meta['duration_timecode'],
                    thumb,
                    filename,
                ),
            )
            conn.commit()
        self._invalidate_clips_cache()

    def _generate_remote_thumbnail(self, url: str, key: str) -> str | None:
        if not shutil.which(self.config.ffmpeg_binary):
            return None
        output = self.thumbnails_dir / f'{key}.jpg'

        def grab(seek: float | None) -> None:
            cmd = [self.config.ffmpeg_binary, '-y', '-hide_banner', '-loglevel', 'error']
            if seek is not None:
                cmd.extend(['-ss', str(seek)])
            cmd.extend(['-i', url, '-frames:v', '1', '-vf', 'scale=256:-2:flags=lanczos',
                        '-q:v', '6', '-map_metadata', '-1', str(output)])
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)

        grab(1.0)
        if not output.exists():
            grab(None)  # live streams / very short clips: take the first frame
        return str(output) if output.exists() else None

    async def get_clip(self, deck_id: int) -> ClipRecord | None:
        clips = await self.list_clips()
        if self._clips_cache is clips:
            return self._clips_index.get(deck_id)
        return next((clip for clip in clips if clip.deck_id == deck_id), None)

    async def rename_clip(self, deck_id: int, name: str) -> ClipRecord | None:
        await asyncio.to_thread(self._rename_clip_sync, deck_id, name)
        return await self.get_clip(deck_id)

    def _rename_clip_sync(self, deck_id: int, name: str) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            row_id = rows[deck_id - 1]['id']
            conn.execute('UPDATE clips SET name = ? WHERE id = ?', (name, row_id))
            conn.commit()
        self._invalidate_clips_cache()

    async def list_folders(self) -> list[str]:
        return await asyncio.to_thread(self._list_folders_sync)

    def _list_folders_sync(self) -> list[str]:
        with self._connect() as conn:
            clip_rows = conn.execute("SELECT DISTINCT folder FROM clips WHERE folder != ''").fetchall()
            folder_rows = conn.execute("SELECT name FROM media_folders ORDER BY name COLLATE NOCASE ASC").fetchall()
        folders = {row['folder'] for row in clip_rows if row['folder']}
        folders.update(row['name'] for row in folder_rows if row['name'])
        folders = sorted(folders, key=str.lower)
        if 'Library' in folders:
            folders.remove('Library')
            folders.insert(0, 'Library')
        if 'System' in folders:
            folders.remove('System')
            folders.append('System')
        return folders

    async def create_folder(self, folder: str) -> str:
        return await asyncio.to_thread(self._create_folder_sync, folder)

    def _create_folder_sync(self, folder: str) -> str:
        folder = (folder or 'Library').strip() or 'Library'
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO media_folders (name) VALUES (?)', (folder,))
            conn.commit()
        self._invalidate_clips_cache()
        return folder

    async def set_folder(self, deck_id: int, folder: str) -> ClipRecord | None:
        await asyncio.to_thread(self._set_folder_sync, deck_id, folder)
        return await self.get_clip(deck_id)

    def _set_folder_sync(self, deck_id: int, folder: str) -> None:
        folder = (folder or 'Library').strip() or 'Library'
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO media_folders (name) VALUES (?)', (folder,))
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            row_id = rows[deck_id - 1]['id']
            conn.execute('UPDATE clips SET folder = ? WHERE id = ?', (folder, row_id))
            conn.commit()
        self._invalidate_clips_cache()

    async def set_loop(self, deck_id: int, enabled: bool) -> ClipRecord | None:
        await asyncio.to_thread(self._set_loop_sync, deck_id, enabled)
        return await self.get_clip(deck_id)

    def _set_loop_sync(self, deck_id: int, enabled: bool) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            row_id = rows[deck_id - 1]['id']
            conn.execute('UPDATE clips SET loop_enabled = ? WHERE id = ?', (1 if enabled else 0, row_id))
            conn.commit()
        self._invalidate_clips_cache()

    async def set_marks(
        self,
        deck_id: int,
        mark_in_seconds: float | None,
        mark_out_seconds: float | None,
    ) -> ClipRecord | None:
        await asyncio.to_thread(self._set_marks_sync, deck_id, mark_in_seconds, mark_out_seconds)
        return await self.get_clip(deck_id)

    def _set_marks_sync(
        self,
        deck_id: int,
        mark_in_seconds: float | None,
        mark_out_seconds: float | None,
    ) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            row_id = rows[deck_id - 1]['id']
            assignments: list[str] = []
            params: list[Any] = []
            if mark_in_seconds is not None:
                assignments.append('mark_in_seconds = ?')
                params.append(max(0.0, float(mark_in_seconds)))
            if mark_out_seconds is not None:
                assignments.append('mark_out_seconds = ?')
                params.append(max(0.0, float(mark_out_seconds)))
            if not assignments:
                return
            params.append(row_id)
            conn.execute(f'UPDATE clips SET {", ".join(assignments)} WHERE id = ?', params)
            conn.commit()
        self._invalidate_clips_cache()

    async def set_tags(self, deck_id: int, tags: str) -> ClipRecord | None:
        await asyncio.to_thread(self._set_tags_sync, deck_id, normalize_tags(tags))
        return await self.get_clip(deck_id)

    def _set_tags_sync(self, deck_id: int, tags: str) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            conn.execute('UPDATE clips SET tags = ? WHERE id = ?', (tags, rows[deck_id - 1]['id']))
            conn.commit()
        self._invalidate_clips_cache()

    async def set_duration(self, deck_id: int, seconds: float) -> ClipRecord | None:
        await asyncio.to_thread(self._set_duration_sync, deck_id, seconds)
        return await self.get_clip(deck_id)

    def _set_duration_sync(self, deck_id: int, seconds: float) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT id, framerate FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            row = rows[deck_id - 1]
            duration = max(0.5, min(float(seconds), 86400.0))
            conn.execute(
                'UPDATE clips SET duration_seconds = ?, duration_timecode = ? WHERE id = ?',
                (duration, seconds_to_timecode(duration, row['framerate'] or 25.0), row['id']),
            )
            conn.commit()
        self._invalidate_clips_cache()

    async def get_audio_levels(self, deck_id: int) -> list[float]:
        return await asyncio.to_thread(self._get_audio_levels_sync, deck_id)

    def _get_audio_levels_sync(self, deck_id: int) -> list[float]:
        with self._connect() as conn:
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return []
            row = conn.execute('SELECT audio_levels FROM clips WHERE id = ?', (rows[deck_id - 1]['id'],)).fetchone()
        if not row or not row['audio_levels']:
            return []
        try:
            levels = json.loads(row['audio_levels'])
        except (TypeError, ValueError):
            return []
        return levels if isinstance(levels, list) else []

    async def export_entries(self) -> list[dict[str, Any]]:
        clips = await self.list_clips()
        return [
            {
                'filename': clip.filename,
                'name': clip.name,
                'folder': clip.folder,
                'loop_enabled': clip.loop_enabled,
                'mark_in_seconds': clip.mark_in_seconds,
                'mark_out_seconds': clip.mark_out_seconds,
                'tags': clip.tags,
                'media_kind': clip.media_kind,
                'duration_seconds': clip.duration_seconds if clip.media_kind == 'image' else None,
            }
            for clip in clips
        ]

    async def apply_import_entries(self, entries: list[dict[str, Any]]) -> int:
        return await asyncio.to_thread(self._apply_import_entries_sync, entries or [])

    def _apply_import_entries_sync(self, entries: list[dict[str, Any]]) -> int:
        applied = 0
        with self._connect() as conn:
            for entry in entries:
                filename = str(entry.get('filename') or '').strip()
                if not filename:
                    continue
                row = conn.execute('SELECT id, framerate, media_kind FROM clips WHERE filename = ?', (filename,)).fetchone()
                if not row:
                    continue
                folder = (str(entry.get('folder') or '') or 'Library').strip() or 'Library'
                conn.execute('INSERT OR IGNORE INTO media_folders (name) VALUES (?)', (folder,))
                assignments = {
                    'name': str(entry.get('name') or filename),
                    'folder': folder,
                    'loop_enabled': 1 if entry.get('loop_enabled') else 0,
                    'mark_in_seconds': max(0.0, float(entry.get('mark_in_seconds') or 0.0)),
                    'mark_out_seconds': max(0.0, float(entry.get('mark_out_seconds') or 0.0)),
                    'tags': normalize_tags(str(entry.get('tags') or '')),
                }
                duration = entry.get('duration_seconds')
                if duration and row['media_kind'] == 'image':
                    clamped = max(0.5, min(float(duration), 86400.0))
                    assignments['duration_seconds'] = clamped
                    assignments['duration_timecode'] = seconds_to_timecode(clamped, row['framerate'] or 25.0)
                keys = ', '.join(f'{key} = ?' for key in assignments)
                conn.execute(f'UPDATE clips SET {keys} WHERE id = ?', (*assignments.values(), row['id']))
                applied += 1
            conn.commit()
        self._invalidate_clips_cache()
        return applied

    async def get_pad_assignments(self) -> dict[int, str]:
        return await asyncio.to_thread(self._get_pad_assignments_sync)

    def _get_pad_assignments_sync(self) -> dict[int, str]:
        with self._connect() as conn:
            rows = conn.execute('SELECT pad, filename FROM pad_assignments').fetchall()
        return {int(row['pad']): row['filename'] for row in rows}

    async def set_pad_assignment(self, pad: int, filename: str | None) -> bool:
        if pad < 1 or pad > 9:
            return False
        await asyncio.to_thread(self._set_pad_assignment_sync, pad, filename)
        return True

    def _set_pad_assignment_sync(self, pad: int, filename: str | None) -> None:
        with self._connect() as conn:
            if filename is None:
                conn.execute('DELETE FROM pad_assignments WHERE pad = ?', (pad,))
            else:
                conn.execute(
                    'INSERT INTO pad_assignments (pad, filename) VALUES (?, ?) '
                    'ON CONFLICT(pad) DO UPDATE SET filename = excluded.filename',
                    (pad, filename),
                )
            conn.commit()

    async def delete_clip(self, deck_id: int) -> None:
        await asyncio.to_thread(self._delete_clip_sync, deck_id)

    async def delete_clips_by_filenames(self, filenames: list[str]) -> int:
        return await asyncio.to_thread(self._delete_clips_by_filenames_sync, filenames)

    def _delete_clips_by_filenames_sync(self, filenames: list[str]) -> int:
        # Filename is the library's stable unique key, unlike the positional
        # deck_id — so bulk deletes resolve the same rows the operator selected
        # even if the list reordered in between.
        names = [name for name in dict.fromkeys(filenames) if name]
        if not names:
            return 0
        deleted = 0
        with self._connect() as conn:
            placeholders = ','.join('?' * len(names))
            rows = conn.execute(
                f'SELECT id, filepath, thumbnail_path FROM clips WHERE filename IN ({placeholders})',
                names,
            ).fetchall()
            for row in rows:
                # filepath may be a USB path (drive maybe gone) or a URL; either
                # way removing the local file is best-effort.
                with contextlib.suppress(OSError):
                    Path(row['filepath']).unlink(missing_ok=True)
                if row['thumbnail_path']:
                    Path(row['thumbnail_path']).unlink(missing_ok=True)
                conn.execute('DELETE FROM clips WHERE id = ?', (row['id'],))
                deleted += 1
            conn.commit()
        self._invalidate_clips_cache()
        return deleted

    def _delete_clip_sync(self, deck_id: int) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if deck_id < 1 or deck_id > len(rows):
                return
            row = rows[deck_id - 1]
            Path(row['filepath']).unlink(missing_ok=True)
            if row['thumbnail_path']:
                Path(row['thumbnail_path']).unlink(missing_ok=True)
            conn.execute('DELETE FROM clips WHERE id = ?', (row['id'],))
            conn.commit()
        self._invalidate_clips_cache()

    async def reorder(self, deck_ids: list[int]) -> None:
        await asyncio.to_thread(self._reorder_sync, deck_ids)

    def _reorder_sync(self, deck_ids: list[int]) -> None:
        with self._connect() as conn:
            rows = conn.execute('SELECT id FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
            if sorted(deck_ids) != list(range(1, len(rows) + 1)):
                return
            ordered_row_ids = [rows[deck_id - 1]['id'] for deck_id in deck_ids]
            for sort_order, row_id in enumerate(ordered_row_ids, start=1):
                conn.execute('UPDATE clips SET sort_order = ? WHERE id = ?', (sort_order, row_id))
            conn.commit()
        self._invalidate_clips_cache()

    def _media_kind_for_path(self, file_path: Path) -> str:
        return 'image' if file_path.suffix.lower() in IMAGE_EXTENSIONS else 'video'

    def _default_duration_for_kind(self, media_kind: str) -> float:
        if media_kind == 'image':
            return float(self.config.default_image_duration_seconds)
        return 0.0


def normalize_tags(raw: str) -> str:
    parts = [part.strip().lower() for part in (raw or '').replace(';', ',').split(',')]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ', '.join(seen)


def parse_rms_levels(stdout: str, max_entries: int = 14400) -> list[float]:
    """Parse ffmpeg ametadata output into one clamped dBFS value per second."""
    levels: list[float] = []
    for line in stdout.splitlines():
        if 'lavfi.astats.Overall.RMS_level=' not in line:
            continue
        raw = line.rsplit('=', 1)[1].strip()
        try:
            value = float(raw)
        except ValueError:
            value = -60.0
        if value != value or value == float('-inf'):  # NaN or silence
            value = -60.0
        levels.append(round(max(-60.0, min(value, 0.0)), 1))
        if len(levels) >= max_entries:
            break
    return levels


def seconds_to_timecode(seconds: float, framerate: float) -> str:
    seconds = max(seconds, 0.0)
    total_frames = int(round(seconds * max(framerate, 1.0)))
    fps = int(round(max(framerate, 1.0)))
    frames = total_frames % fps
    total_seconds = total_frames // fps
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f'{hrs:02d}:{mins:02d}:{secs:02d}:{frames:02d}'
