from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterable


REBOOT_HELPER_PATH = '/usr/local/bin/deckpilot-system-reboot'
REBOOT_REQUIRED_PATHS = (
    'scripts/show_boot_ip.py',
)


def changed_files_between(repo_root: Path, from_commit: str | None, to_commit: str | None) -> list[str]:
    if not from_commit or not to_commit or from_commit == to_commit:
        return []
    try:
        completed = subprocess.run(
            ['git', 'diff', '--name-only', from_commit, to_commit],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def build_update_plan(
    changed_files: Iterable[str] | None,
    *,
    platform_name: str,
    install_mode: str,
    automatic_reboot_available: bool,
    update_available: bool | None,
) -> dict[str, Any]:
    files = sorted(set(changed_files or []))
    reboot_triggers = [path for path in files if _requires_reboot(path)]
    can_reboot_platform = platform_name == 'linux' and install_mode == 'systemd'

    reboot_required: bool | None
    if reboot_triggers and can_reboot_platform:
        reboot_required = True
    elif files or update_available is False:
        reboot_required = False
    else:
        reboot_required = None

    if reboot_required is True:
        restart_target = 'raspberry_pi'
        if automatic_reboot_available:
            restart_notice = 'This update will reboot the Raspberry Pi automatically.'
        else:
            restart_notice = 'This update requires a Raspberry Pi reboot, but automatic reboot is not configured on this installation yet.'
        restart_reason = 'This update changes Raspberry Pi appliance components outside the DeckPilot process.'
    elif reboot_required is False:
        restart_target = 'deckpilot'
        restart_notice = 'This update only restarts DeckPilot. No Raspberry Pi reboot is required.'
        restart_reason = 'No system component requiring a reboot was detected in this update.'
    else:
        restart_target = 'auto'
        restart_notice = 'DeckPilot will decide during the update whether a Raspberry Pi reboot is needed.'
        restart_reason = 'Remote changes could not be fully analyzed yet.'

    return {
        'reboot_required': reboot_required,
        'automatic_reboot_available': automatic_reboot_available,
        'restart_target': restart_target,
        'restart_notice': restart_notice,
        'restart_reason': restart_reason,
        'reboot_trigger_files': reboot_triggers,
        'changed_file_count': len(files),
    }


def _requires_reboot(path: str) -> bool:
    return any(path == candidate or path.startswith(f'{candidate}/') for candidate in REBOOT_REQUIRED_PATHS)
