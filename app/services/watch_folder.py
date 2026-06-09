from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Dict, Tuple

from app.core.config import AppConfig

Snapshot = Dict[str, Tuple[int, int]]


class WatchFolderService:
    """Light periodic scanner for the clips directory.

    Files dropped over SMB / USB are picked up automatically: a file is only
    ingested once its size and mtime are identical across two consecutive
    scans, so half-copied files never enter the library. One os.scandir every
    few seconds is the entire steady-state cost.
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

    async def start(self) -> None:
        if not self.enabled or self._task:
            return
        # The startup refresh already ingested what is on disk right now.
        self._ingested = await asyncio.to_thread(self._scan)
        self._last_scan = self._ingested
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
        previous = self._last_scan
        self._last_scan = scan
        if previous is None or scan != previous or scan == self._ingested:
            return False
        added = [name for name in scan if self._ingested is None or name not in self._ingested]
        removed = [name for name in (self._ingested or {}) if name not in scan]
        self._ingested = scan
        if added:
            await self.state.add_log('info', 'media', f'Watch folder: ingesting {len(added)} new file(s): {", ".join(sorted(added)[:5])}')
        if removed:
            await self.state.add_log('info', 'media', f'Watch folder: {len(removed)} file(s) removed from disk.')
        await self.controller.refresh_clips()
        return True

    def _scan(self) -> Snapshot:
        snapshot: Snapshot = {}
        allowed = set(self.config.allowed_upload_extensions)
        try:
            with os.scandir(self.config.clips_dir) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    suffix = os.path.splitext(entry.name)[1].lower()
                    if suffix not in allowed:
                        continue
                    stats = entry.stat()
                    snapshot[entry.name] = (stats.st_size, stats.st_mtime_ns)
        except OSError:
            return self._last_scan or {}
        return snapshot
