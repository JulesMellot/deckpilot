from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import List

from app.core.models import PlaylistItem, PlaylistSummary
from app.media.clip_store import ClipStore


class PlaylistStore:
    def __init__(self, db_path: str, clip_store: ClipStore) -> None:
        self.db_path = Path(db_path)
        self.clip_store = clip_store

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
            conn.commit()

    async def ensure_default_playlist(self) -> None:
        await asyncio.to_thread(self._ensure_default_playlist_sync)

    def _ensure_default_playlist_sync(self) -> None:
        with self._connect() as conn:
            row = conn.execute('SELECT id FROM playlists WHERE is_active = 1').fetchone()
            if row:
                return
            conn.execute('UPDATE playlists SET is_active = 0')
            conn.execute('INSERT OR IGNORE INTO playlists (name, is_active) VALUES (?, 1)', ('Main Playlist',))
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
            conn.commit()

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
            conn.commit()

    async def get_active_playlist(self) -> dict:
        return await asyncio.to_thread(self._get_active_playlist_sync)

    def _get_active_playlist_sync(self) -> dict:
        with self._connect() as conn:
            playlist = conn.execute('SELECT * FROM playlists WHERE is_active = 1 ORDER BY id LIMIT 1').fetchone()
            if not playlist:
                return {'playlist': None, 'items': []}
            items = conn.execute('SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC', (playlist['id'],)).fetchall()
        clips = asyncio.run(self.clip_store.list_clips())
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
                ).to_dict()
            )
        return {
            'playlist': PlaylistSummary(id=playlist['id'], name=playlist['name'], is_active=True, item_count=len(payload)).to_dict(),
            'items': payload,
        }

    async def sync_active_playlist_from_clips(self) -> None:
        clips = await self.clip_store.list_clips()
        await asyncio.to_thread(self._sync_active_playlist_from_clips_sync, [clip.deck_id for clip in clips])

    def _sync_active_playlist_from_clips_sync(self, deck_ids: list[int]) -> None:
        with self._connect() as conn:
            playlist = conn.execute('SELECT id FROM playlists WHERE is_active = 1 ORDER BY id LIMIT 1').fetchone()
            if not playlist:
                return
            playlist_id = playlist['id']
            existing = conn.execute('SELECT clip_id FROM playlist_items WHERE playlist_id = ? ORDER BY sort_order ASC, id ASC', (playlist_id,)).fetchall()
            existing_ids = [row['clip_id'] for row in existing]
            if existing_ids == deck_ids:
                return
            conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
            for sort_order, clip_id in enumerate(deck_ids, start=1):
                conn.execute('INSERT INTO playlist_items (playlist_id, sort_order, clip_id, loop_enabled, auto_advance) VALUES (?, ?, ?, 0, 0)', (playlist_id, sort_order, clip_id))
            conn.commit()

    async def reorder_active_playlist(self, clip_ids: list[int]) -> None:
        await asyncio.to_thread(self._reorder_active_playlist_sync, clip_ids)

    def _reorder_active_playlist_sync(self, clip_ids: list[int]) -> None:
        with self._connect() as conn:
            playlist = conn.execute('SELECT id FROM playlists WHERE is_active = 1 ORDER BY id LIMIT 1').fetchone()
            if not playlist:
                return
            playlist_id = playlist['id']
            conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
            for sort_order, clip_id in enumerate(clip_ids, start=1):
                conn.execute('INSERT INTO playlist_items (playlist_id, sort_order, clip_id, loop_enabled, auto_advance) VALUES (?, ?, ?, 0, 0)', (playlist_id, sort_order, clip_id))
            conn.commit()
