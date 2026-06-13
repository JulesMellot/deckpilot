from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Where Linux desktops / Raspberry Pi OS auto-mount removable media. A USB
# drive plugged into the Pi lands under one of these as /media/<user>/<label>.
REMOVABLE_ROOTS: Tuple[str, ...] = ('/media', '/mnt', '/run/media')

# Pseudo / virtual filesystems that never hold clips. The list is deliberately
# broad so only real, mountable volumes are ever treated as media sources.
_VIRTUAL_FSTYPES = frozenset({
    'proc', 'sysfs', 'devtmpfs', 'tmpfs', 'devpts', 'cgroup', 'cgroup2',
    'overlay', 'squashfs', 'mqueue', 'debugfs', 'tracefs', 'configfs',
    'securityfs', 'pstore', 'autofs', 'fusectl', 'bpf', 'ramfs', 'efivarfs',
    'hugetlbfs', 'binfmt_misc', 'nsfs', 'rpc_pipefs', 'fuse.gvfsd-fuse',
    'fuse.portal',
})

DiskUsage = Callable[[str], Any]


@dataclass
class StorageDevice:
    """A mounted volume DeckPilot reads clips from (internal disk or USB)."""

    id: str  # the mountpoint — the stable handle the UI uses
    label: str
    mountpoint: str
    device: str
    fstype: str
    total_bytes: int
    free_bytes: int
    removable: bool
    is_internal: bool  # holds the built-in clip library / upload target

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'mountpoint': self.mountpoint,
            'device': self.device,
            'fstype': self.fstype,
            'total_bytes': self.total_bytes,
            'free_bytes': self.free_bytes,
            'removable': self.removable,
            'is_internal': self.is_internal,
        }


def _unescape_mount_field(field: str) -> str:
    # /proc/mounts encodes spaces, tabs and backslashes as octal escapes.
    if '\\' not in field:
        return field
    out: List[str] = []
    i = 0
    while i < len(field):
        if field[i] == '\\' and i + 3 < len(field) and field[i + 1:i + 4].isdigit():
            out.append(chr(int(field[i + 1:i + 4], 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return ''.join(out)


def parse_mounts(text: str) -> List[Tuple[str, str, str]]:
    """Parse /proc/mounts into (device, mountpoint, fstype) triples."""
    entries: List[Tuple[str, str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device = _unescape_mount_field(parts[0])
        mountpoint = _unescape_mount_field(parts[1])
        fstype = parts[2]
        entries.append((device, mountpoint, fstype))
    return entries


def _read_mounts(mounts_text: Optional[str]) -> List[Tuple[str, str, str]]:
    if mounts_text is None:
        try:
            mounts_text = Path('/proc/mounts').read_text(encoding='utf-8')
        except OSError:
            mounts_text = ''
    return parse_mounts(mounts_text)


def _is_removable(mountpoint: str) -> bool:
    return any(mountpoint == root or mountpoint.startswith(root + '/') for root in REMOVABLE_ROOTS)


def _enclosing_mountpoint(path: str, mountpoints: List[str]) -> Optional[str]:
    # The volume whose mountpoint is the longest prefix of the path.
    target = Path(os.path.normpath(path))
    best: Optional[str] = None
    for mountpoint in mountpoints:
        mp = Path(mountpoint)
        if mp == target or mp in target.parents:
            if best is None or len(mountpoint) > len(best):
                best = mountpoint
    return best


def _label_for(mountpoint: str, removable: bool) -> str:
    if mountpoint == '/':
        return 'Internal (SD card)'
    name = Path(mountpoint).name or mountpoint
    return name if removable else f'{name} (internal)'


def removable_media_roots(mounts_text: Optional[str] = None) -> List[str]:
    """Mountpoints of currently-connected removable drives, real filesystems only.

    These are the extra roots DeckPilot scans for clips alongside the internal
    library, so a USB drive plugged in after boot is picked up on the next scan.
    """
    roots: List[str] = []
    seen: set[str] = set()
    for _device, mountpoint, fstype in _read_mounts(mounts_text):
        if not _is_removable(mountpoint) or fstype in _VIRTUAL_FSTYPES:
            continue
        if mountpoint in seen:
            continue
        seen.add(mountpoint)
        roots.append(mountpoint)
    return roots


def list_storage_devices(
    internal_dir: str,
    *,
    mounts_text: Optional[str] = None,
    usage: DiskUsage = shutil.disk_usage,
) -> List[StorageDevice]:
    """Volumes shown on the storage panel: the internal disk plus every USB drive."""
    entries = _read_mounts(mounts_text)
    all_mountpoints = [mp for _, mp, _ in entries]
    internal_mp = _enclosing_mountpoint(internal_dir, all_mountpoints)

    # Last mount of a given point wins (later mounts shadow earlier ones).
    by_mountpoint: Dict[str, Tuple[str, str]] = {}
    for device, mountpoint, fstype in entries:
        by_mountpoint[mountpoint] = (device, fstype)

    devices: List[StorageDevice] = []
    for mountpoint, (device, fstype) in by_mountpoint.items():
        removable = _is_removable(mountpoint)
        is_internal = mountpoint == internal_mp
        if not removable and not is_internal:
            continue
        if fstype in _VIRTUAL_FSTYPES:
            continue
        try:
            disk = usage(mountpoint)
        except OSError:
            continue
        devices.append(StorageDevice(
            id=mountpoint,
            label='Internal (SD card)' if is_internal else _label_for(mountpoint, removable),
            mountpoint=mountpoint,
            device=device,
            fstype=fstype,
            total_bytes=int(disk.total),
            free_bytes=int(disk.free),
            removable=removable,
            is_internal=is_internal,
        ))

    # Always surface the internal disk, even when /proc/mounts is unavailable
    # (e.g. a non-Linux dev machine), so the panel is never empty.
    if not any(d.is_internal for d in devices):
        try:
            disk = usage(internal_dir)
            devices.append(StorageDevice(
                id=internal_dir,
                label='Internal (SD card)',
                mountpoint=internal_dir,
                device='',
                fstype='',
                total_bytes=int(disk.total),
                free_bytes=int(disk.free),
                removable=False,
                is_internal=True,
            ))
        except OSError:
            pass

    devices.sort(key=lambda d: (not d.is_internal, d.mountpoint))
    return devices
