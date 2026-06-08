from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import shutil
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from app.services.update_policy import REBOOT_HELPER_PATH, build_update_plan, changed_files_between


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='DeckPilot detached update runner')
    parser.add_argument('--repo-root', required=True)
    parser.add_argument('--status-path', required=True)
    parser.add_argument('--parent-pid', required=True, type=int)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--python-executable', required=True)
    parser.add_argument('--config-path')
    parser.add_argument('--service-name')
    return parser.parse_args()


def read_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_status(path: Path, **updates: Any) -> None:
    payload = read_status(path)
    payload.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
        handle.write('\n')


def run_command(command: list[str], cwd: Path, env: dict[str, str], timeout: int = 900) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or '').strip()
        raise RuntimeError(stderr or f'Command failed: {" ".join(command)}')
    return completed.stdout.strip()


def pip_command(repo_root: Path, python_executable: str) -> list[str]:
    if platform.system().lower() == 'windows':
        pip_path = repo_root / '.venv' / 'Scripts' / 'pip.exe'
    else:
        pip_path = repo_root / '.venv' / 'bin' / 'pip'
    if pip_path.exists():
        return [str(pip_path), 'install', '-r', str(repo_root / 'requirements.txt')]
    return [python_executable, '-m', 'pip', 'install', '-r', str(repo_root / 'requirements.txt')]


def terminate_process(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
        return
    except OSError:
        pass
    if platform.system().lower() == 'windows':
        subprocess.run(
            ['taskkill', '/PID', str(pid), '/T', '/F'],
            capture_output=True,
            text=True,
            check=False,
        )


def wait_for_process_exit(pid: int, timeout: int = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)


def start_app(repo_root: Path, python_executable: str, env: dict[str, str]) -> None:
    command = [python_executable, '-m', 'app.main']
    kwargs: dict[str, Any] = {
        'cwd': str(repo_root),
        'env': env,
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
    }
    if platform.system().lower() == 'windows':
        kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen(command, **kwargs)


def automatic_reboot_available(service_name: str | None) -> bool:
    return bool(
        platform.system().lower() == 'linux'
        and service_name
        and shutil.which('sudo')
        and Path(REBOOT_HELPER_PATH).exists()
    )


def reboot_system() -> None:
    completed = subprocess.run(
        ['sudo', '-n', REBOOT_HELPER_PATH],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip()
        raise RuntimeError(detail or 'Automatic Raspberry Pi reboot failed.')


def wait_for_http(port: int, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    url = f'http://127.0.0.1:{port}/api/state'
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1.5)
    return False


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    status_path = Path(args.status_path).resolve()
    env = os.environ.copy()
    if args.config_path:
        env['PIDECK_CONFIG'] = args.config_path

    try:
        if not (repo_root / '.git').exists():
            raise RuntimeError('Automatic update requires a Git checkout.')
        if not (repo_root / 'requirements.txt').exists():
            raise RuntimeError('requirements.txt is missing from this installation.')

        write_status(status_path, phase='running', message='Pulling the latest DeckPilot version...')
        previous_commit = run_command(['git', 'rev-parse', '--short', 'HEAD'], repo_root, env, timeout=15)
        previous_commit_full = run_command(['git', 'rev-parse', 'HEAD'], repo_root, env, timeout=15)
        branch = run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], repo_root, env, timeout=15)

        remote_commit = None
        try:
            remote_output = run_command(['git', 'ls-remote', '--heads', 'origin', branch], repo_root, env, timeout=20)
            if remote_output:
                remote_commit = remote_output.split()[0][:7]
        except RuntimeError:
            remote_commit = None

        pull_output = run_command(['git', 'pull', '--ff-only'], repo_root, env, timeout=300)

        write_status(
            status_path,
            phase='running',
            message='Installing updated Python dependencies...',
            branch=branch,
            previous_commit=previous_commit,
            remote_commit=remote_commit,
        )
        run_command(pip_command(repo_root, args.python_executable), repo_root, env, timeout=900)
        current_commit = run_command(['git', 'rev-parse', '--short', 'HEAD'], repo_root, env, timeout=15)
        current_commit_full = run_command(['git', 'rev-parse', 'HEAD'], repo_root, env, timeout=15)

        update_plan = build_update_plan(
            changed_files_between(repo_root, previous_commit_full, current_commit_full),
            platform_name=platform.system().lower(),
            install_mode='systemd' if args.service_name else 'manual',
            automatic_reboot_available=automatic_reboot_available(args.service_name),
            update_available=current_commit != previous_commit,
        )

        if current_commit == previous_commit and 'Already up to date.' in pull_output:
            write_status(
                status_path,
                phase='success',
                message='DeckPilot is already up to date.',
                finished_at=time.time(),
                current_commit=current_commit,
                current_commit_full=current_commit_full,
                error=None,
            )
            return

        if update_plan['reboot_required'] is True and update_plan['automatic_reboot_available']:
            write_status(
                status_path,
                phase='rebooting',
                message='Redemarrage du Raspberry Pi pour appliquer la mise a jour...',
                current_commit=current_commit,
                current_commit_full=current_commit_full,
                reboot_required=True,
                automatic_reboot_available=True,
                restart_target=update_plan['restart_target'],
                restart_notice=update_plan['restart_notice'],
                restart_reason=update_plan['restart_reason'],
                reboot_trigger_files=update_plan['reboot_trigger_files'],
            )
            terminate_process(args.parent_pid)
            wait_for_process_exit(args.parent_pid)
            time.sleep(1.0)
            reboot_system()
            return

        restart_message = 'Restarting DeckPilot to apply the update...'
        if update_plan['reboot_required'] is True and not update_plan['automatic_reboot_available']:
            restart_message = 'DeckPilot va redemarrer maintenant. Un redemarrage manuel du Raspberry Pi restera requis apres la mise a jour.'
        write_status(
            status_path,
            phase='restarting',
            message=restart_message,
            current_commit=current_commit,
            current_commit_full=current_commit_full,
            reboot_required=update_plan['reboot_required'],
            automatic_reboot_available=update_plan['automatic_reboot_available'],
            restart_target=update_plan['restart_target'],
            restart_notice=update_plan['restart_notice'],
            restart_reason=update_plan['restart_reason'],
            reboot_trigger_files=update_plan['reboot_trigger_files'],
        )

        terminate_process(args.parent_pid)
        wait_for_process_exit(args.parent_pid)

        if not args.service_name:
            start_app(repo_root, args.python_executable, env)

        if not wait_for_http(args.port):
            raise RuntimeError('DeckPilot did not come back online after the update.')

        write_status(
            status_path,
            phase='success',
            message=(
                'DeckPilot updated successfully. Un redemarrage manuel du Raspberry Pi reste requis.'
                if update_plan['reboot_required'] and not update_plan['automatic_reboot_available']
                else 'DeckPilot updated successfully.'
            ),
            finished_at=time.time(),
            current_commit=current_commit,
            current_commit_full=current_commit_full,
            reboot_required=update_plan['reboot_required'],
            automatic_reboot_available=update_plan['automatic_reboot_available'],
            restart_target=update_plan['restart_target'],
            restart_notice=update_plan['restart_notice'],
            restart_reason=update_plan['restart_reason'],
            reboot_trigger_files=update_plan['reboot_trigger_files'],
            error=None,
        )
    except Exception as exc:
        write_status(
            status_path,
            phase='error',
            message='Automatic update failed.',
            error=str(exc),
            finished_at=time.time(),
        )


if __name__ == '__main__':
    main()
