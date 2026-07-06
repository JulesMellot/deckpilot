import json

from app.services.storage_maintenance import _dev_name, parse_lsblk


def _lsblk(devices):
    return json.dumps({'blockdevices': devices})


def test_parse_lsblk_finds_unmounted_removable_partition():
    text = _lsblk([
        {
            'name': 'sda', 'path': '/dev/sda', 'fstype': None, 'label': None,
            'size': 32000000000, 'mountpoint': None, 'rm': True, 'type': 'disk',
            'children': [
                {'name': 'sda1', 'path': '/dev/sda1', 'fstype': 'exfat', 'label': 'SHOW',
                 'size': 31999000000, 'mountpoint': None, 'rm': True, 'type': 'part'},
            ],
        },
    ])
    found = parse_lsblk(text)
    assert len(found) == 1
    assert found[0]['device'] == '/dev/sda1'
    assert found[0]['fstype'] == 'exfat'
    assert found[0]['label'] == 'SHOW'


def test_parse_lsblk_skips_mounted_and_internal():
    text = _lsblk([
        # Internal SD card: not removable, mounted — never listed.
        {
            'name': 'mmcblk0', 'path': '/dev/mmcblk0', 'fstype': None, 'label': None,
            'size': 16000000000, 'mountpoint': None, 'rm': False, 'type': 'disk',
            'children': [
                {'name': 'mmcblk0p2', 'path': '/dev/mmcblk0p2', 'fstype': 'ext4', 'label': None,
                 'size': 15000000000, 'mountpoint': '/', 'rm': False, 'type': 'part'},
            ],
        },
        # Healthy USB drive, already mounted — handled by the eject path instead.
        {
            'name': 'sdb', 'path': '/dev/sdb', 'fstype': None, 'label': None,
            'size': 64000000000, 'mountpoint': None, 'rm': True, 'type': 'disk',
            'children': [
                {'name': 'sdb1', 'path': '/dev/sdb1', 'fstype': 'vfat', 'label': 'CLIPS',
                 'size': 63000000000, 'mountpoint': '/media/deckpilot/CLIPS', 'rm': True, 'type': 'part'},
            ],
        },
    ])
    assert parse_lsblk(text) == []


def test_parse_lsblk_handles_new_mountpoints_array_and_inherited_rm():
    # Newer lsblk: "mountpoints": [null]; removability sometimes only on the disk.
    text = _lsblk([
        {
            'name': 'sdc', 'path': '/dev/sdc', 'fstype': None, 'label': None,
            'size': 8000000000, 'mountpoints': [None], 'rm': True, 'type': 'disk',
            'children': [
                {'name': 'sdc1', 'path': '/dev/sdc1', 'fstype': 'ntfs', 'label': 'NTFS_DRIVE',
                 'size': 7900000000, 'mountpoints': [None], 'rm': False, 'type': 'part'},
            ],
        },
    ])
    found = parse_lsblk(text)
    assert len(found) == 1
    assert found[0]['name'] == 'sdc1'
    assert found[0]['fstype'] == 'ntfs'


def test_parse_lsblk_partitionless_stick_and_no_fstype():
    text = _lsblk([
        # Whole-disk filesystem (no partition table): repairable as-is.
        {'name': 'sdd', 'path': '/dev/sdd', 'fstype': 'vfat', 'label': 'RAWSTICK',
         'size': 4000000000, 'mountpoint': None, 'rm': True, 'type': 'disk'},
        # No detectable filesystem: nothing fsck could target, skipped.
        {'name': 'sde', 'path': '/dev/sde', 'fstype': None, 'label': None,
         'size': 4000000000, 'mountpoint': None, 'rm': True, 'type': 'disk'},
    ])
    found = parse_lsblk(text)
    assert [entry['name'] for entry in found] == ['sdd']


def test_parse_lsblk_garbage_input():
    assert parse_lsblk('') == []
    assert parse_lsblk('not json') == []
    assert parse_lsblk('{}') == []


def test_dev_name_validation():
    assert _dev_name('/dev/sda1') == 'sda1'
    assert _dev_name('/dev/mmcblk0p2') == 'mmcblk0p2'
    # Traversal or option injection never reaches sudo.
    assert _dev_name('/dev/../etc/passwd') is None
    assert _dev_name('/dev/sda1; rm -rf /') is None
    assert _dev_name('--version') is None
