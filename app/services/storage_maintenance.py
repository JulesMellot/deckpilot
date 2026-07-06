from __future__ import annotations

"""Safe-eject and filesystem repair for removable drives.

Both actions go through the root helper that bootstrap.sh installs
(/usr/local/bin/deckpilot-usb-mount) via passwordless sudo — the service
runs as an unprivileged user and umount/fsck need root. Without the helper
(dev machine, install that predates it) eject falls back to a plain umount
and repair explains how to get the helper.
"""

import asyncio
import json
import platform
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

HELPER_PATH = '/usr/local/bin/deckpilot-usb-mount'

# Kernel device names only (sdb1, mmcblk0p2, nvme0n1p1) — this string ends up
# as a sudo argument, so anything else is rejected outright.
_DEV_NAME_RE = re.compile(r'^[a-zA-Z0-9]+$')

_HELPER_HINT = 'Run scripts/bootstrap.sh once on the Pi to install the storage helper.'


async def _run(*argv: str) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except (FileNotFoundError, OSError) as exc:
        return 127, str(exc)
    out, _ = await process.communicate()
    return process.returncode or 0, out.decode('utf-8', errors='replace').strip()


def parse_lsblk(text: str) -> List[Dict[str, Any]]:
    """Unmounted removable partitions from `lsblk -J` output — the drives the
    repair button targets: plugged in, but nothing mounted them (usually a
    dirty filesystem after an unclean pull)."""
    try:
        tree = json.loads(text or '{}')
    except json.JSONDecodeError:
        return []
    found: List[Dict[str, Any]] = []

    def mounted(entry: Dict[str, Any]) -> bool:
        # Newer lsblk emits "mountpoints": [null], older a single "mountpoint".
        points = entry.get('mountpoints')
        if points is None:
            points = [entry.get('mountpoint')]
        return any(point for point in points)

    def walk(entries: List[Dict[str, Any]], parent_removable: bool) -> None:
        for entry in entries or []:
            removable = bool(entry.get('rm')) or bool(entry.get('hotplug')) or parent_removable
            children = entry.get('children') or []
            # A disk with partitions is handled through them; a partitionless
            # stick is its own filesystem entry.
            if not children and removable and entry.get('fstype') and not mounted(entry):
                name = str(entry.get('name') or '')
                if _DEV_NAME_RE.match(name):
                    found.append({
                        'name': name,
                        'device': str(entry.get('path') or f'/dev/{name}'),
                        'fstype': str(entry.get('fstype')),
                        'label': str(entry.get('label') or name),
                        'size_bytes': int(entry.get('size') or 0),
                    })
            walk(children, removable)

    walk(tree.get('blockdevices') or [], False)
    return found


async def list_unmounted_removables() -> List[Dict[str, Any]]:
    if platform.system().lower() != 'linux':
        return []
    code, out = await _run('lsblk', '-J', '-b', '-o', 'NAME,PATH,FSTYPE,LABEL,SIZE,MOUNTPOINT,RM,HOTPLUG,TYPE')
    if code != 0:
        return []
    return parse_lsblk(out)


def _dev_name(device: str) -> Optional[str]:
    # Exactly `/dev/<name>` (or a bare name) — no traversal, no options.
    name = Path(device).name
    if not _DEV_NAME_RE.match(name) or device not in (name, f'/dev/{name}'):
        return None
    return name


def _helper_available() -> bool:
    return platform.system().lower() == 'linux' and Path(HELPER_PATH).exists()


async def eject_drive(device: str, mountpoint: str) -> tuple[bool, str]:
    """Flush and unmount so the drive can be pulled without a dirty filesystem."""
    name = _dev_name(device)
    if _helper_available() and name:
        code, out = await _run('sudo', '-n', HELPER_PATH, 'eject', name)
        if code == 0:
            return True, 'Drive ejected — safe to unplug.'
        return False, out or f'Eject failed. {_HELPER_HINT}'
    # No helper: try a plain umount — works for user mounts and on dev machines.
    code, out = await _run('umount', mountpoint)
    if code == 0:
        return True, 'Drive ejected — safe to unplug.'
    return False, out or f'Eject failed. {_HELPER_HINT}'


async def repair_drive(device: str) -> tuple[bool, str]:
    """fsck/ntfsfix an unmounted drive, then remount it. Root-only, so the
    helper is required."""
    name = _dev_name(device)
    if not name:
        return False, f'Invalid device: {device}'
    if not _helper_available():
        return False, f'Repair needs the root helper. {_HELPER_HINT}'
    code, out = await _run('sudo', '-n', HELPER_PATH, 'repair', name)
    if code == 0:
        return True, 'Repair finished — the drive was remounted.'
    return False, out or 'Repair failed.'
