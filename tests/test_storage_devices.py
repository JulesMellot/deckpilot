from __future__ import annotations

import unittest
from collections import namedtuple

from app.services.storage_devices import (
    list_storage_devices,
    parse_mounts,
    removable_media_roots,
)

Usage = namedtuple('Usage', ['total', 'used', 'free'])

# A representative slice of a Raspberry Pi's /proc/mounts with a USB drive
# auto-mounted under /media/pi.
PI_MOUNTS = '\n'.join([
    'proc /proc proc rw 0 0',
    'sysfs /sys sysfs rw 0 0',
    '/dev/mmcblk0p2 / ext4 rw 0 0',
    '/dev/mmcblk0p1 /boot vfat rw 0 0',
    'tmpfs /run tmpfs rw 0 0',
    '/dev/sda1 /media/pi/FIELD\\040DRIVE exfat rw 0 0',
])


def fake_usage(mountpoint: str) -> Usage:
    sizes = {
        '/': Usage(32_000_000_000, 20_000_000_000, 12_000_000_000),
        '/boot': Usage(256_000_000, 56_000_000, 200_000_000),
        '/media/pi/FIELD DRIVE': Usage(2_000_000_000_000, 100_000_000_000, 1_900_000_000_000),
    }
    if mountpoint not in sizes:
        raise OSError('no such mount')
    return sizes[mountpoint]


class ParseMountsTests(unittest.TestCase):
    def test_decodes_octal_escaped_spaces(self) -> None:
        entries = parse_mounts(PI_MOUNTS)
        usb = [mp for _, mp, _ in entries if mp.startswith('/media')]
        self.assertEqual(usb, ['/media/pi/FIELD DRIVE'])


class RemovableMediaRootsTests(unittest.TestCase):
    def test_lists_only_connected_removable_drives(self) -> None:
        roots = removable_media_roots(PI_MOUNTS)
        self.assertEqual(roots, ['/media/pi/FIELD DRIVE'])

    def test_empty_when_no_usb(self) -> None:
        mounts = '/dev/mmcblk0p2 / ext4 rw 0 0\ntmpfs /run tmpfs rw 0 0'
        self.assertEqual(removable_media_roots(mounts), [])


class ListStorageDevicesTests(unittest.TestCase):
    def test_lists_internal_disk_and_removable_drive(self) -> None:
        devices = list_storage_devices(
            '/home/pi/deckpilot/runtime/clips', mounts_text=PI_MOUNTS, usage=fake_usage,
        )
        mountpoints = [d.mountpoint for d in devices]
        self.assertEqual(mountpoints, ['/', '/media/pi/FIELD DRIVE'])
        # /boot is neither internal nor removable, so it is hidden.
        self.assertNotIn('/boot', mountpoints)

    def test_marks_the_disk_holding_the_library_internal(self) -> None:
        devices = list_storage_devices(
            '/home/pi/deckpilot/runtime/clips', mounts_text=PI_MOUNTS, usage=fake_usage,
        )
        internal = next(d for d in devices if d.is_internal)
        self.assertEqual(internal.mountpoint, '/')
        self.assertFalse(internal.removable)
        usb = next(d for d in devices if d.removable)
        self.assertFalse(usb.is_internal)
        self.assertEqual(usb.free_bytes, 1_900_000_000_000)

    def test_skips_volumes_with_unreadable_usage(self) -> None:
        mounts = PI_MOUNTS + '\n/dev/sdb1 /media/pi/GHOST ext4 rw 0 0'
        devices = list_storage_devices(
            '/home/pi/deckpilot/runtime/clips', mounts_text=mounts, usage=fake_usage,
        )
        self.assertNotIn('/media/pi/GHOST', [d.mountpoint for d in devices])


if __name__ == '__main__':
    unittest.main()
