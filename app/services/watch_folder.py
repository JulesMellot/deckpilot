from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import Any, Dict, Tuple

from app.core.config import AppConfig
from app.services.storage_devices import removable_media_roots

Snapshot = Dict[str, Tuple[int, int]]


def _path_under(root: str, path: str) -> bool:
    root = os.path.normpath(root)
    path = os.path.normpath(path)
    return path == root or path.startswith(root + os.sep)


class WatchFolderService:
    """Light periodic scanner for the clip sources.

    Scans the internal clips directory plus any connected USB drive, so a drive
    plugged in after boot is picked up on the next tick. Files dropped over
    SMB / USB are ingested only once their size and mtime are identical across
    two consecutive scans, so half-copied files never enter the library. A
    drive appearing or disappearing also shows up as a snapshot change, which
    triggers a refresh that flips its clips online / offline.
    """

    def __init__(self, config: AppConfig, state, controller) -> None:
        self.config = config
        self.state = state
        self.controller = controller
        self.interval = max(2.0, float(config.watch_folder_seconds or 0.0))
        self.enabled = float(config.watch_folder_seconds or 0.0) > 0
        self._task: asyncio.Task | None = None
        self._last_scan: Snapshot | None = None
        self._ingested: Snapshot | None = None
        # Roots readable in the most recent _scan (set as a side effect), and
        # the set seen on the previous tick — a change means a drive came or
        # went, which must trigger a refresh even when no files changed.
        self._current_roots: list[str] = []
        self._present_roots: set[str] | None = None
        self.last_ingest_at: float | None = None
        self.ingest_count: int = 0
        self.pending_files: int = 0

    def snapshot(self) -> Dict[str, Any]:
        return {
            'enabled': self.enabled,
            'interval_seconds': self.interval,
            'path': self.config.clips_dir,
            'last_ingest_at': self.last_ingest_at,
            'ingest_count': self.ingest_count,
            'pending_files': self.pending_files,
        }

    async def start(self) -> None:
        if not self.enabled or self._task:
            return
        # The startup refresh already ingested what is on disk right now.
        self._ingested = await asyncio.to_thread(self._scan)
        self._last_scan = self._ingested
        self._present_roots = set(self._current_roots)
        self._task = asyncio.create_task(self._run())
        await self.state.add_log('info', 'media', f'Watch folder active on {self.config.clips_dir} (every {self.interval:.0f}s).')

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.tick()
            except Exception:
                # A failed scan (e.g. unmounted share) must never kill the loop.
                continue

    async def tick(self) -> bool:
        scan = await asyncio.to_thread(self._scan)
        scanned_set = set(self._current_roots)
        # A drive that browns out / re-enumerates (common with bus-powered USB
        # disks on a Pi) drops out of the scan for a tick. Keep its last-known
        # files so that flap doesn't masquerade as a mass delete-then-re-add.
        if self._ingested:
            for path, value in self._ingested.items():
                if not any(_path_under(root, path) for root in scanned_set):
                    scan.setdefault(path, value)
        roots_changed = self._present_roots is not None and scanned_set != self._present_roots
        self._present_roots = scanned_set

        previous = self._last_scan
        self._last_scan = scan
        ingested = self._ingested or {}

        # Per-file stability: a path is settled once its size+mtime are identical
        # across two consecutive scans. A big drop is ingested progressively —
        # each file joins the enrichment queue the moment *it* finishes copying,
        # instead of holding the whole batch until the last byte of the last file.
        settled = {path for path, value in scan.items() if previous is not None and previous.get(path) == value}
        # Newly settled files (or files re-copied to a new size/mtime) to ingest.
        ready = {path: scan[path] for path in settled if ingested.get(path) != scan[path]}
        # Treat a file as removed only once it is absent for two consecutive scans,
        # so a one-tick flap (USB re-enumeration) is never read as a deletion.
        removed = [path for path in ingested if path not in scan and path not in (previous or {})]

        # Anything seen but not yet settled is still copying: surface it as pending.
        self.pending_files = sum(1 for path, value in scan.items() if path not in settled and ingested.get(path) != value)

        if not ready and not removed and not roots_changed:
            return False

        for path, value in ready.items():
            ingested[path] = value
        for path in removed:
            ingested.pop(path, None)
        self._ingested = ingested

        if ready or removed:
            self.last_ingest_at = time.time()
            self.ingest_count += 1
        if ready:
            names = sorted(os.path.basename(path) for path in ready)
            await self.state.add_log('info', 'media', f'Watch folder: ingesting {len(ready)} new file(s): {", ".join(names[:5])}')
        if removed:
            await self.state.add_log('info', 'media', f'Watch folder: {len(removed)} file(s) removed from disk.')
        # Hand the controller only the settled paths so still-copying files in the
        # same batch are left for a later tick. Drive appear/disappear also forces
        # a refresh so clips flip online / offline even when their set is unchanged.
        if ready or removed or roots_changed:
            await self.controller.refresh_clips(settle_paths=settled)
        return True

    def _source_roots(self) -> list[str]:
        roots = [self.config.clips_dir]
        for mount in removable_media_roots():
            if mount not in roots:
                roots.append(mount)
        return roots

    def _scan(self) -> Snapshot:
        snapshot: Snapshot = {}
        allowed = set(self.config.allowed_upload_extensions)
        scanned: list[str] = []
        for root in self._source_roots():
            collected: Snapshot = {}
            try:
                with os.scandir(root) as entries:
                    for entry in entries:
                        # Skip dotfiles, incl. macOS AppleDouble sidecars (._*)
                        # and .DS_Store that ride along on USB/SMB copies.
                        if entry.name.startswith('.'):
                            continue
                        if os.path.splitext(entry.name)[1].lower() not in allowed:
                            continue
                        if not entry.is_file():
                            continue
                        stats = entry.stat()
                        # Key by full path so identically-named files on
                        # different drives don't shadow one another.
                        collected[entry.path] = (stats.st_size, stats.st_mtime_ns)
            except OSError:
                # A single unreadable / vanished root must not blank the scan;
                # leave it out of `scanned` so its files are retained, not dropped.
                continue
            scanned.append(root)
            snapshot.update(collected)
        self._current_roots = scanned
        return snapshot
