from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import List

from app.core.models import PlaylistItem, PlaylistSummary
from app.media.clip_store import ClipStore

END_BEHAVIORS = ('next', 'stop', 'hold', 'loop')


class PlaylistStore:
    def __init__(self, db_path: str, clip_store: ClipStore) -> None:
        self.db_path = Path(db_path)
        self.clip_store = clip_store

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout = 5000')
        conn.execute('PRAGMA synchronous = NORMAL')
        return conn

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)
        await self.ensure_default_playlist()

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    clip_id INTEGER NOT NULL,
                    loop_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_advance INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                )
                '''
            )
            playlist_columns = [row[1] for row in conn.execute('PRAGMA table_info(playlists)').fetchall()]
            if 'auto_sync' not in playlist_columns:
                conn.execute("ALTER TABLE playlists ADD COLUMN auto_sync INTEGER NOT NULL DEFAULT 0")
                # The historical default playlist mirrored the library; keep that behavior.
                conn.execute("UPDATE playlists SET auto_sync = 1 WHERE name = 'Main Playlist'")
            item_columns = [row[1] for row in conn.execute('PRAGMA table_info(playlist_items)').fetchall()]
            if 'end_behavior' not in item_columns:
                conn.execute("ALTER TABLE playlist_items ADD COLUMN end_behavior TEXT NOT NULL DEFAULT 'next'")
            if 'is_music' not in item_columns:
                # Music beds don't count toward the on-air countdown.
                conn.execute("ALTER TABLE playlist_items ADD COLUMN is_music INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    async def ensure_default_playlist(self) -> None:
        await asyncio.to_thread(self._ensure_default_playlist_sync)

    def _ensure_default_playlist_sync(self) -> None:
        with self._connect() as conn:
            row = conn.execute('SELECT id FROM playlists WHERE is_active = 1').fetchone()
            if row:
                return
            # Fall back to an existing playlist before creating "Main Playlist":
            # INSERT OR IGNORE alone would leave no active playlist when the
            # default already exists but lost its active flag.
            existing = conn.execute('SELECT id FROM playlists ORDER BY id ASC LIMIT 1').fetchone()
            if existing:
                conn.execute('UPDATE playlists SET is_active = 1 WHERE id = ?', (existing['id'],))
            else:
                conn.execute('INSERT INTO playlists (name, is_active, auto_sync) VALUES (?, 1, 1)', ('Main Playlist',))
            conn.commit()

    async def list_playlists(self) -> List[dict]:
        return await asyncio.to_thread(self._list_playlists_sync)

    def _list_playlists_sync(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT p.id, p.name, p.is_active, COUNT(i.id) AS item_count
                FROM playlists p
                LEFT JOIN playlist_items i ON i.playlist_id = p.id
                GROUP BY p.id, p.name, p.is_active
                ORDER BY p.id ASC
                '''
            ).fetchall()
        return [PlaylistSummary(id=row['id'], name=row['name'], is_active=bool(row['is_active']), item_count=row['item_count']).to_dict() for row in rows]

    async def create_playlist(self, name: str, clip_ids: list[int] | None = None, activate: bool = False) -> dict:
        return await asyncio.to_thread(self._create_playlist_sync, name, clip_ids or [], activate)

    def _create_playlist_sync(self, name: str, clip_ids: list[int], activate: bool) -> dict:
        clean_name = (name or '').strip() or 'New Playlist'
        with self._connect() as conn:
            if activate:
                conn.execute('UPDATE playlists SET is_active = 0')
            cursor = conn.execute('INSERT INTO playlists (name, is_active) VALUES (?, ?)', (clean_name, 1 if activate else 0))
            playlist_id = cursor.lastrowid
            for sort_order, clip_id in enumerate(clip_ids, start=1):
                conn.execute(
                    'INSERT INTO playlist_items (playlist_id, sort_order, clip_id, loop_enabled, auto_advance) VALUES (?, ?, ?, 0, 0)',
                    (playlist_id, sort_order, clip_id),
                )
            conn.commit()
        return {'id': playlist_id, 'name': clean_name, 'is_active': activate, 'item_count': len(clip_ids)}

    async def activate_playlist(self, playlist_id: int) -> None:
        await asyncio.to_thread(self._activate_playlist_sync, playlist_id)

    def _activate_playlist_sync(self, playlist_id: int) -> None:
        with self._connect() as conn:
            conn.execute('UPDATE playlists SET is_active = 0')
            conn.execute('UPDATE playlists SET is_active = 1 WHERE id = ?', (playlist_id,))
            conn.commit()

    async def rename_playlist(self, playlist_id: int, name: str) -> bool:
        return await asyncio.to_thread(self._rename_playlist_sync, playlist_id, name)

    def _rename_playlist_sync(self, playlist_id: int, name: str) -> bool:
        clean_name = (name or '').strip()
        if not clean_name:
            return False
        with self._connect() as conn:
            try:
                cursor = conn.execute('UPDATE playlists SET name = ? WHERE id = ?', (clean_name, playlist_id))
            except sqlite3.IntegrityError:
                return False
            conn.commit()
            return cursor.rowcount > 0

    async def delete_playlist(self, playlist_id: int) -> bool:
        return await asyncio.to_thread(self._delete_playlist_sync, playlist_id)

    def _delete_playlist_sync(self, playlist_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute('SELECT is_active FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
            if not row:
                return False
            # PRAGMA foreign_keys is off by default: delete the items explicitly.
            conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
            conn.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
            conn.commit()
        if row['is_active']:
            self._ensure_default_playlist_sync()
        return True

    async def add_clip_to_playlist(self, playlist_id: int, clip_id: int) -> None:
        await asyncio.to_thread(self._add_clip_to_playlist_sync, playlist_id, clip_id)

    def _add_clip_to_playlist_sync(self, playlist_id: int, clip_id: int) -> None:
        with self._connect() as conn:
            next_order = conn.execute(
                'SELECT COALESCE(MAX(sort_order), 0) + 1 FROM playlist_items WHERE playlist_id = ?',
                (playlist_id,),
            ).fetchone()[0]
            conn.execute(
                'INSERT INTO playlist_items (playlist_id, sort_order, clip_id, loop_enabled, auto_advance) VALUES (?, ?, ?, 0, 0)',
                (playlist_id, next_order, clip_id),
            )
            self._mark_manual(conn, playlist_id)
            conn.commit()

    def _mark_manual(self, conn: sqlite3.Connection, playlist_id: int) -> None:
        """An edited playlist stops mirroring the media library and becomes a rundown."""
        conn.execute('UPDATE playlists SET auto_sync = 0 WHERE id = ?', (playlist_id,))

    async def set_item_end_behavior(self, playlist_id: int, position: int, behavior: str) -> bool:
        if behavior not in END_BEHAVIORS:
            return False
        return await asyncio.to_thread(self._set_item_end_behavior_sync, playlist_id, position, behavior)

    def _set_item_end_behavior_sync(self, playlist_id: int, position: int, behavior: str) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            if position < 1 or position > len(rows):
                return False
            # End behaviors survive mirror re-syncs (matched by clip), so this
            # does not need to break auto-sync.
            conn.execute('UPDATE playlist_items SET end_behavior = ? WHERE id = ?', (behavior, rows[position - 1]['id']))
            conn.commit()
        return True

    async def set_item_music(self, playlist_id: int, position: int, is_music: bool) -> bool:
        return await asyncio.to_thread(self._set_item_music_sync, playlist_id, position, is_music)

    def _set_item_music_sync(self, playlist_id: int, position: int, is_music: bool) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            if position < 1 or position > len(rows):
                return False
            # Like end behaviors, the music flag survives mirror re-syncs.
            conn.execute('UPDATE playlist_items SET is_music = ? WHERE id = ?', (1 if is_music else 0, rows[position - 1]['id']))
            conn.commit()
        return True

    async def reorder_items(self, playlist_id: int, positions: list[int]) -> bool:
        return await asyncio.to_thread(self._reorder_items_sync, playlist_id, positions)

    def _reorder_items_sync(self, playlist_id: int, positions: list[int]) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            if sorted(positions) != list(range(1, len(rows) + 1)):
                return False
            for sort_order, position in enumerate(positions, start=1):
                conn.execute('UPDATE playlist_items SET sort_order = ? WHERE id = ?', (sort_order, rows[position - 1]['id']))
            self._mark_manual(conn, playlist_id)
            conn.commit()
        return True

    async def remove_item_from_playlist(self, playlist_id: int, position: int) -> None:
        await asyncio.to_thread(self._remove_item_from_playlist_sync, playlist_id, position)

    def _remove_item_from_playlist_sync(self, playlist_id: int, position: int) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            if position < 1 or position > len(rows):
                return
            conn.execute('DELETE FROM playlist_items WHERE id = ?', (rows[position - 1]['id'],))
            remaining = conn.execute(
                'SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            for sort_order, row in enumerate(remaining, start=1):
                conn.execute('UPDATE playlist_items SET sort_order = ? WHERE id = ?', (sort_order, row['id']))
            self._mark_manual(conn, playlist_id)
            conn.commit()

    async def clear_playlist(self, playlist_id: int) -> None:
        await asyncio.to_thread(self._clear_playlist_sync, playlist_id)

    def _clear_playlist_sync(self, playlist_id: int) -> None:
        with self._connect() as conn:
            conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
            self._mark_manual(conn, playlist_id)
            conn.commit()

    async def get_active_playlist(self) -> dict:
        raw = await asyncio.to_thread(self._get_playlist_rows_sync, None)
        if raw is None:
            return {'playlist': None, 'items': []}
        playlist, items = raw
        # The clip list comes from the in-memory cache, not a nested event loop.
        clips = await self.clip_store.list_clips()
        return self._build_playlist_payload(playlist, items, clips)

    async def get_playlist(self, playlist_id: int) -> dict:
        raw = await asyncio.to_thread(self._get_playlist_rows_sync, playlist_id)
        if raw is None:
            return {'playlist': None, 'items': []}
        playlist, items = raw
        clips = await self.clip_store.list_clips()
        return self._build_playlist_payload(playlist, items, clips)

    def _get_playlist_rows_sync(self, playlist_id: int | None):
        """Rows for one playlist; None selects the active playlist."""
        with self._connect() as conn:
            if playlist_id is None:
                playlist = conn.execute('SELECT * FROM playlists WHERE is_active = 1 ORDER BY id LIMIT 1').fetchone()
            else:
                playlist = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
            if not playlist:
                return None
            items = conn.execute('SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC', (playlist['id'],)).fetchall()
        return playlist, items

    def _build_playlist_payload(self, playlist, items, clips) -> dict:
        clip_map = {clip.deck_id: clip for clip in clips}
        payload = []
        for index, row in enumerate(items, start=1):
            clip = clip_map.get(row['clip_id'])
            if not clip:
                continue
            payload.append(
                PlaylistItem(
                    position=index,
                    clip_id=clip.deck_id,
                    clip_name=clip.name,
                    duration_timecode=clip.duration_timecode,
                    loop_enabled=bool(row['loop_enabled']),
                    auto_advance=bool(row['auto_advance']),
                    end_behavior=row['end_behavior'] or 'next',
                    # A clip flagged as music in the library is music in every rundown.
                    is_music=bool(row['is_music']) or clip.is_music,
                ).to_dict()
            )
        return {
            'playlist': PlaylistSummary(id=playlist['id'], name=playlist['name'], is_active=bool(playlist['is_active']), item_count=len(payload)).to_dict(),
            'items': payload,
        }

    async def sync_active_playlist_from_clips(self) -> None:
        clips = await self.clip_store.list_clips()
        await asyncio.to_thread(self._sync_active_playlist_from_clips_sync, [clip.deck_id for clip in clips])

    def _sync_active_playlist_from_clips_sync(self, deck_ids: list[int]) -> None:
        with self._connect() as conn:
            playlist = conn.execute('SELECT id, auto_sync FROM playlists WHERE is_active = 1 ORDER BY id LIMIT 1').fetchone()
            if not playlist:
                return
            playlist_id = playlist['id']
            if not playlist['auto_sync']:
                # Manually curated rundown: only drop items whose clip no longer exists.
                valid = set(deck_ids)
                rows = conn.execute(
                    'SELECT id, clip_id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                    (playlist_id,),
                ).fetchall()
                stale = [row['id'] for row in rows if row['clip_id'] not in valid]
                if stale:
                    conn.executemany('DELETE FROM playlist_items WHERE id = ?', [(row_id,) for row_id in stale])
                    remaining = conn.execute(
                        'SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                        (playlist_id,),
                    ).fetchall()
                    for sort_order, row in enumerate(remaining, start=1):
                        conn.execute('UPDATE playlist_items SET sort_order = ? WHERE id = ?', (sort_order, row['id']))
                    conn.commit()
                return
            existing = conn.execute(
                'SELECT clip_id, loop_enabled, auto_advance, end_behavior, is_music FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            existing_ids = [row['clip_id'] for row in existing]
            if existing_ids == deck_ids:
                return
            self._rewrite_items(conn, playlist_id, deck_ids, existing)
            conn.commit()

    def _rewrite_items(self, conn: sqlite3.Connection, playlist_id: int, clip_ids: list[int], existing_rows) -> None:
        flags = {}
        for row in existing_rows:
            flags.setdefault(row['clip_id'], (row['loop_enabled'], row['auto_advance'], row['end_behavior'] or 'next', row['is_music']))
        conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
        for sort_order, clip_id in enumerate(clip_ids, start=1):
            loop_enabled, auto_advance, end_behavior, is_music = flags.get(clip_id, (0, 0, 'next', 0))
            conn.execute(
                'INSERT INTO playlist_items (playlist_id, sort_order, clip_id, loop_enabled, auto_advance, end_behavior, is_music) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (playlist_id, sort_order, clip_id, loop_enabled, auto_advance, end_behavior, is_music),
            )

    async def reorder_active_playlist(self, clip_ids: list[int]) -> None:
        await asyncio.to_thread(self._reorder_active_playlist_sync, clip_ids)

    def _reorder_active_playlist_sync(self, clip_ids: list[int]) -> None:
        with self._connect() as conn:
            playlist = conn.execute('SELECT id, auto_sync FROM playlists WHERE is_active = 1 ORDER BY id LIMIT 1').fetchone()
            if not playlist or not playlist['auto_sync']:
                return
            playlist_id = playlist['id']
            existing = conn.execute(
                'SELECT clip_id, loop_enabled, auto_advance, end_behavior, is_music FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                (playlist_id,),
            ).fetchall()
            self._rewrite_items(conn, playlist_id, clip_ids, existing)
            conn.commit()

    async def export_playlists(self, clip_filenames: dict[int, str]) -> list[dict]:
        return await asyncio.to_thread(self._export_playlists_sync, clip_filenames)

    def _export_playlists_sync(self, clip_filenames: dict[int, str]) -> list[dict]:
        with self._connect() as conn:
            playlists = conn.execute('SELECT * FROM playlists ORDER BY id ASC').fetchall()
            payload = []
            for playlist in playlists:
                items = conn.execute(
                    'SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC',
                    (playlist['id'],),
                ).fetchall()
                payload.append({
                    'name': playlist['name'],
                    'is_active': bool(playlist['is_active']),
                    'auto_sync': bool(playlist['auto_sync']),
                    'items': [
                        {
                            'filename': clip_filenames.get(row['clip_id']),
                            'loop_enabled': bool(row['loop_enabled']),
                            'end_behavior': row['end_behavior'] or 'next',
                            'is_music': bool(row['is_music']),
                        }
                        for row in items
                        if clip_filenames.get(row['clip_id'])
                    ],
                })
        return payload

    async def apply_import(self, playlists: list[dict], clip_ids_by_filename: dict[str, int]) -> int:
        return await asyncio.to_thread(self._apply_import_sync, playlists or [], clip_ids_by_filename)

    def _apply_import_sync(self, playlists: list[dict], clip_ids_by_filename: dict[str, int]) -> int:
        applied = 0
        with self._connect() as conn:
            for entry in playlists:
                name = str(entry.get('name') or '').strip()
                if not name:
                    continue
                row = conn.execute('SELECT id FROM playlists WHERE name = ?', (name,)).fetchone()
                if row:
                    playlist_id = row['id']
                else:
                    playlist_id = conn.execute(
                        'INSERT INTO playlists (name, is_active, auto_sync) VALUES (?, 0, 0)', (name,)
                    ).lastrowid
                conn.execute(
                    'UPDATE playlists SET auto_sync = ? WHERE id = ?',
                    (1 if entry.get('auto_sync') else 0, playlist_id),
                )
                conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
                sort_order = 0
                for item in entry.get('items') or []:
                    clip_id = clip_ids_by_filename.get(str(item.get('filename') or ''))
                    if not clip_id:
                        continue
                    sort_order += 1
                    behavior = item.get('end_behavior') if item.get('end_behavior') in END_BEHAVIORS else 'next'
                    conn.execute(
                        'INSERT INTO playlist_items (playlist_id, sort_order, clip_id, loop_enabled, auto_advance, end_behavior, is_music) VALUES (?, ?, ?, ?, 0, ?, ?)',
                        (playlist_id, sort_order, clip_id, 1 if item.get('loop_enabled') else 0, behavior, 1 if item.get('is_music') else 0),
                    )
                if entry.get('is_active'):
                    conn.execute('UPDATE playlists SET is_active = 0')
                    conn.execute('UPDATE playlists SET is_active = 1 WHERE id = ?', (playlist_id,))
                applied += 1
            conn.commit()
        return applied
