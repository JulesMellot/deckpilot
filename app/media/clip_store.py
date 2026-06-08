from __future__ import annotations

import asyncio
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Iterable, List

from app.core.config import AppConfig
from app.core.models import ClipRecord


class ClipStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db_path = Path(config.db_path)
        self.clips_dir = Path(config.clips_dir)
        self.thumbnails_dir = Path(config.thumbnails_dir)

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)
        await self.ensure_builtin_clips()
        await self.sync_with_disk()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
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
                    is_vertical INTEGER NOT NULL DEFAULT 0,
                    thumbnail_path TEXT,
                    loop_enabled INTEGER NOT NULL DEFAULT 0,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
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
            columns = [row[1] for row in conn.execute("PRAGMA table_info(clips)").fetchall()]
            if 'folder' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN folder TEXT NOT NULL DEFAULT 'Library'")
            if 'width' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN width INTEGER NOT NULL DEFAULT 0")
            if 'height' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN height INTEGER NOT NULL DEFAULT 0")
            if 'is_vertical' not in columns:
                conn.execute("ALTER TABLE clips ADD COLUMN is_vertical INTEGER NOT NULL DEFAULT 0")
            conn.execute("INSERT OR IGNORE INTO media_folders (name) VALUES ('Library')")
            conn.execute("INSERT OR IGNORE INTO media_folders (name) VALUES ('System')")
            conn.commit()

    async def sync_with_disk(self) -> None:
        await asyncio.to_thread(self._sync_with_disk_sync)

    def _sync_with_disk_sync(self) -> None:
        files = [
            p for p in self.clips_dir.iterdir()
            if p.is_file() and p.suffix.lower() in self.config.allowed_upload_extensions
        ]
        with self._connect() as conn:
            existing = {row['filename']: row for row in conn.execute('SELECT * FROM clips').fetchall()}
            sort_seed = conn.execute('SELECT COALESCE(MAX(sort_order), 0) FROM clips').fetchone()[0]

            for file_path in files:
                if file_path.name in existing:
                    row = existing[file_path.name]
                    if not row['width'] or not row['height']:
                        meta = self._probe_clip(file_path)
                        conn.execute(
                            '''
                            UPDATE clips
                            SET width = ?, height = ?, is_vertical = ?, codec = ?, framerate = ?, duration_seconds = ?, duration_timecode = ?
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
                                file_path.name,
                            ),
                        )
                    continue
                sort_seed += 1
                meta = self._probe_clip(file_path)
                thumb = self._generate_thumbnail(file_path)
                conn.execute(
                    """
                    INSERT INTO clips (
                        sort_order, name, folder, filename, filepath, duration_seconds, duration_timecode,
                        framerate, codec, width, height, is_vertical, thumbnail_path, loop_enabled, is_builtin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                    """,
                    (
                        sort_seed,
                        file_path.stem,
                        'Library',
                        file_path.name,
                        str(file_path),
                        meta['duration_seconds'],
                        meta['duration_timecode'],
                        meta['framerate'],
                        meta['codec'],
                        meta['width'],
                        meta['height'],
                        1 if meta['is_vertical'] else 0,
                        thumb,
                    ),
                )

            disk_names = {item.name for item in files}
            for row in conn.execute('SELECT filename, thumbnail_path FROM clips WHERE is_builtin = 0').fetchall():
                if row['filename'] not in disk_names:
                    if row['thumbnail_path']:
                        Path(row['thumbnail_path']).unlink(missing_ok=True)
                    conn.execute('DELETE FROM clips WHERE filename = ?', (row['filename'],))
            conn.commit()

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
                        framerate, codec, width, height, is_vertical, thumbnail_path, loop_enabled, is_builtin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
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
                        1 if meta['is_vertical'] else 0,
                        thumb,
                    ),
                )
            conn.commit()

    def _probe_clip(self, file_path: Path) -> dict:
        if not shutil.which(self.config.ffprobe_binary):
            return {
                'duration_seconds': 0.0,
                'duration_timecode': '00:00:00:00',
                'framerate': self.config.default_framerate,
                'codec': 'unknown',
                'width': 0,
                'height': 0,
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
            str(file_path),
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        duration_seconds = 0.0
        framerate = self.config.default_framerate
        codec = 'unknown'
        width = 0
        height = 0
        for line in result.stdout.splitlines():
            if line.startswith('duration='):
                duration_seconds = float(line.split('=', 1)[1] or 0)
            elif line.startswith('r_frame_rate='):
                raw = line.split('=', 1)[1]
                if '/' in raw:
                    num, den = raw.split('/', 1)
                    if float(den or 1) != 0:
                        framerate = round(float(num) / float(den), 2)
            elif line.startswith('codec_name=') and codec == 'unknown':
                codec = line.split('=', 1)[1]
            elif line.startswith('width=') and width == 0:
                width = int(float(line.split('=', 1)[1] or 0))
            elif line.startswith('height=') and height == 0:
                height = int(float(line.split('=', 1)[1] or 0))
        return {
            'duration_seconds': duration_seconds,
            'duration_timecode': seconds_to_timecode(duration_seconds, framerate),
            'framerate': framerate,
            'codec': codec,
            'width': width,
            'height': height,
            'is_vertical': bool(height and width and height > width),
        }

    def _generate_thumbnail(self, file_path: Path) -> str | None:
        if not shutil.which(self.config.ffmpeg_binary):
            return None
        output = self.thumbnails_dir / f'{file_path.stem}.jpg'
        cmd = [
            self.config.ffmpeg_binary,
            '-y',
            '-i',
            str(file_path),
            '-vf',
            'thumbnail,scale=320:-1',
            '-frames:v',
            '1',
            str(output),
        ]
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(output) if output.exists() else None

    async def save_uploads(self, uploads: Iterable[tuple[str, bytes]]) -> None:
        for filename, content in uploads:
            destination = self.clips_dir / Path(filename).name
            destination.write_bytes(content)
        await self.sync_with_disk()

    async def list_clips(self) -> List[ClipRecord]:
        return await asyncio.to_thread(self._list_clips_sync)

    def _list_clips_sync(self) -> List[ClipRecord]:
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM clips ORDER BY sort_order ASC, id ASC').fetchall()
        clips: list[ClipRecord] = []
        for index, row in enumerate(rows, start=1):
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
                    is_vertical=bool(row['is_vertical']),
                    thumbnail_path=row['thumbnail_path'],
                    loop_enabled=bool(row['loop_enabled']),
                    is_builtin=bool(row['is_builtin']),
                )
            )
        return clips

    async def get_clip(self, deck_id: int) -> ClipRecord | None:
        clips = await self.list_clips()
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

    async def delete_clip(self, deck_id: int) -> None:
        await asyncio.to_thread(self._delete_clip_sync, deck_id)

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
