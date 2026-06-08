from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.core.config import AppConfig
from app.core.state import AppState


class UpdateManager:
    def __init__(self, config: AppConfig, state: AppState) -> None:
        self.config = config
        self.state = state
        self.repo_root = Path(__file__).resolve().parents[2]
        self.status_path = Path(config.data_dir) / 'update_status.json'
        self._lock = asyncio.Lock()

    async def get_status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_status_sync)

    async def trigger_update(self) -> dict[str, Any]:
        async with self._lock:
            status = await self.get_status()
            if not status['can_update']:
                raise RuntimeError(status['reason'] or 'Automatic update is not available for this installation.')

            started_at = time.time()
            payload = {
                'phase': 'running',
                'message': 'Update started. DeckPilot will restart automatically if needed.',
                'started_at': started_at,
                'finished_at': None,
                'error': None,
                'runner_pid': None,
                'service_name': status.get('service_name'),
                'branch': status.get('branch'),
                'previous_commit': status.get('current_commit'),
                'current_commit': status.get('current_commit'),
                'remote_commit': status.get('remote_commit'),
            }
            await asyncio.to_thread(self._write_status_sync, payload)
            runner_pid = await asyncio.to_thread(self._spawn_runner_sync, status)
            payload['runner_pid'] = runner_pid
            await asyncio.to_thread(self._write_status_sync, payload)
            await self.state.add_log('info', 'updater', 'Web update requested.')
            return await self.get_status()

    def _spawn_runner_sync(self, status: dict[str, Any]) -> int:
        command = [
            sys.executable,
            '-m',
            'app.services.update_runner',
            '--repo-root',
            str(self.repo_root),
            '--status-path',
            str(self.status_path),
            '--parent-pid',
            str(os.getpid()),
            '--port',
            str(self.config.http_port),
            '--python-executable',
            sys.executable,
        ]
        config_path = os.environ.get('PIDECK_CONFIG')
        if config_path:
            command.extend(['--config-path', config_path])
        if status.get('service_name'):
            command.extend(['--service-name', str(status['service_name'])])

        env = os.environ.copy()
        proc = subprocess.Popen(
            command,
            cwd=str(self.repo_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid

    def _get_status_sync(self) -> dict[str, Any]:
        saved = self._read_status_sync()
        platform_name = platform.system().lower() or sys.platform.lower()
        service_name = self._detect_service_name_sync()
        git_available = shutil.which('git') is not None
        git_checkout = (self.repo_root / '.git').exists()
        bootstrap_sh = (self.repo_root / 'scripts' / 'bootstrap.sh').exists()
        bootstrap_ps1 = (self.repo_root / 'scripts' / 'bootstrap.ps1').exists()

        branch = None
        current_commit = None
        current_commit_full = None
        remote_commit = None
        remote_commit_full = None
        update_available = None

        if git_available and git_checkout:
            branch = self._git_output(['rev-parse', '--abbrev-ref', 'HEAD'])
            current_commit = self._git_output(['rev-parse', '--short', 'HEAD'])
            current_commit_full = self._git_output(['rev-parse', 'HEAD'])
            remote_commit_full = self._remote_commit_full(branch)
            if remote_commit_full:
                remote_commit = remote_commit_full[:7]
            if current_commit_full and remote_commit_full:
                update_available = current_commit_full != remote_commit_full

        phase = str(saved.get('phase') or 'idle')
        runner_pid = saved.get('runner_pid')
        runner_active = self._pid_exists(int(runner_pid)) if runner_pid else False
        saved_previous_commit = saved.get('previous_commit')
        saved_current_commit = saved.get('current_commit')
        saved_remote_commit = saved.get('remote_commit')

        # On systemd installs the detached updater can be killed with the old service cgroup
        # even though the new DeckPilot process is already running. Normalize that state here.
        if phase == 'restarting' and not runner_active:
            update_applied = bool(
                current_commit
                and (
                    (saved_previous_commit and current_commit != saved_previous_commit)
                    or (saved_current_commit and current_commit == saved_current_commit)
                    or (saved_remote_commit and current_commit == saved_remote_commit)
                )
            )
            if update_applied:
                phase = 'success'
                saved['phase'] = 'success'
                saved['message'] = 'DeckPilot updated successfully.'
                saved['finished_at'] = saved.get('finished_at') or time.time()
                saved['error'] = None
                saved['current_commit'] = current_commit
                self._write_status_sync(saved)
        elif phase in {'running', 'restarting'} and not runner_active and saved.get('finished_at'):
            phase = str(saved.get('phase'))

        reason = None
        if not git_available:
            reason = 'Git is not available on this system.'
        elif not git_checkout:
            reason = 'Automatic update requires a Git-based DeckPilot installation.'
        elif phase in {'running', 'restarting'} and runner_active:
            reason = 'An update is already in progress.'

        return {
            'phase': phase,
            'message': saved.get('message') or self._default_message(update_available),
            'started_at': saved.get('started_at'),
            'finished_at': saved.get('finished_at'),
            'error': saved.get('error'),
            'runner_pid': runner_pid,
            'runner_active': runner_active,
            'platform': platform_name,
            'repo_root': str(self.repo_root),
            'install_mode': 'systemd' if service_name else 'manual',
            'service_name': service_name,
            'git_available': git_available,
            'git_checkout': git_checkout,
            'bootstrap_available': bootstrap_sh if platform_name != 'windows' else bootstrap_ps1,
            'branch': branch,
            'current_commit': current_commit,
            'remote_commit': remote_commit,
            'update_available': update_available,
            'can_update': reason is None,
            'reason': reason,
        }

    def _default_message(self, update_available: bool | None) -> str:
        if update_available is True:
            return 'A newer version is available.'
        if update_available is False:
            return 'DeckPilot is up to date.'
        return 'Automatic update is ready.'

    def _remote_commit_full(self, branch: str | None) -> str | None:
        if not branch:
            return None
        output = self._git_output(['ls-remote', '--heads', 'origin', branch], timeout=12)
        if not output:
            output = self._git_output(['ls-remote', 'origin', 'HEAD'], timeout=12)
        if not output:
            return None
        return output.split()[0]

    def _git_output(self, args: list[str], timeout: int = 8) -> str | None:
        try:
            completed = subprocess.run(
                ['git', *args],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        value = completed.stdout.strip()
        return value or None

    def _detect_service_name_sync(self) -> str | None:
        if platform.system().lower() != 'linux' or shutil.which('systemctl') is None:
            return None
        current_pid = os.getpid()
        for candidate in ('deckpilot.service', 'pideck-open.service'):
            try:
                completed = subprocess.run(
                    ['systemctl', 'show', candidate, '--property', 'MainPID', '--value'],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if completed.returncode != 0:
                continue
            if completed.stdout.strip() == str(current_pid):
                return candidate
        return None

    def _read_status_sync(self) -> dict[str, Any]:
        if not self.status_path.exists():
            return {}
        try:
            with self.status_path.open('r', encoding='utf-8') as handle:
                payload = json.load(handle)
                return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_status_sync(self, payload: dict[str, Any]) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with self.status_path.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2)
            handle.write('\n')

    def _pid_exists(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
