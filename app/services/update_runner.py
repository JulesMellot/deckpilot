from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import shutil
import sys
import threading
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
        base = [str(pip_path)]
    else:
        base = [python_executable, '-m', 'pip']
    # --no-input: pip must never sit waiting for an invisible prompt (keyring,
    # index auth) — that reads as "the updater is stuck" to the operator.
    # Fewer retries: on a dead venue network, pip's default 5 retries with
    # backoff stall for minutes before surfacing the real error.
    # --upgrade: no-op for the ==-pinned packages, but keeps the deliberately
    # unpinned yt-dlp fresh — YouTube breaks old extractors within months.
    return [*base, 'install', '--upgrade', '--no-input', '--retries', '2', '--progress-bar', 'off',
            '-r', str(repo_root / 'requirements.txt')]


def run_streaming(command: list[str], cwd: Path, env: dict[str, str], status_path: Path, timeout: int = 900) -> None:
    """Run a slow command with its latest output line mirrored into the status
    file, so the UI shows life instead of a frozen message. Kills the process
    when the total budget is exhausted — even if it went silent."""
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []

    def _drain() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            stripped = raw.strip()
            if stripped:
                lines.append(stripped)

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()

    deadline = time.time() + timeout
    shown: str | None = None
    while process.poll() is None:
        if time.time() > deadline:
            process.kill()
            reader.join(timeout=5)
            raise RuntimeError(f'{command[0]} timed out after {timeout // 60} minutes: '
                               f'{lines[-1] if lines else "no output"}')
        latest = lines[-1] if lines else None
        if latest and latest != shown:
            shown = latest
            write_status(status_path, detail=latest[:200])
        time.sleep(1.0)
    reader.join(timeout=5)
    if process.returncode != 0:
        raise RuntimeError('\n'.join(lines[-15:]) or f'Command failed: {" ".join(command)}')


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


def wait_for_process_exit(pid: int, timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.5)
    return False


def stop_parent(pid: int, term_timeout: int = 20) -> None:
    """SIGTERM the running server, escalating to SIGKILL if it will not die.
    A graceful uvicorn shutdown can hang on open websockets; the old process
    must exit or systemd never restarts the service and the update stalls."""
    terminate_process(pid)
    if wait_for_process_exit(pid, timeout=term_timeout):
        return
    if platform.system().lower() == 'windows':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, text=True, check=False)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    wait_for_process_exit(pid, timeout=10)


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

        write_status(status_path, phase='running', step=1, steps_total=4, detail=None,
                     message='Pulling the latest DeckPilot version...')
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

        current_commit = run_command(['git', 'rev-parse', '--short', 'HEAD'], repo_root, env, timeout=15)
        current_commit_full = run_command(['git', 'rev-parse', 'HEAD'], repo_root, env, timeout=15)
        changed_files = changed_files_between(repo_root, previous_commit_full, current_commit_full)

        # The pip pass is the slowest, most fragile step of the whole update
        # (minutes on a Pi 3, worse on venue Wi-Fi) — only pay for it when the
        # pulled commits actually touched requirements.txt.
        if 'requirements.txt' in changed_files:
            write_status(
                status_path,
                phase='running',
                step=2,
                detail=None,
                message='Installing updated Python dependencies...',
                branch=branch,
                previous_commit=previous_commit,
                remote_commit=remote_commit,
            )
            # pip's version self-check is one more PyPI round-trip that can
            # stall on a captive/venue network; it has no business in an update.
            pip_env = dict(env, PIP_DISABLE_PIP_VERSION_CHECK='1')
            run_streaming(pip_command(repo_root, args.python_executable), repo_root, pip_env, status_path, timeout=900)
        else:
            write_status(
                status_path,
                phase='running',
                step=2,
                detail=None,
                message='Python dependencies unchanged — skipping reinstall.',
                branch=branch,
                previous_commit=previous_commit,
                remote_commit=remote_commit,
            )

        update_plan = build_update_plan(
            changed_files,
            platform_name=platform.system().lower(),
            install_mode='systemd' if args.service_name else 'manual',
            automatic_reboot_available=automatic_reboot_available(args.service_name),
            update_available=current_commit != previous_commit,
        )

        if current_commit == previous_commit and 'Already up to date.' in pull_output:
            write_status(
                status_path,
                phase='success',
                step=4,
                detail=None,
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
                step=3,
                detail=None,
                message='Rebooting the Raspberry Pi to apply the update...',
                current_commit=current_commit,
                current_commit_full=current_commit_full,
                reboot_required=True,
                automatic_reboot_available=True,
                restart_target=update_plan['restart_target'],
                restart_notice=update_plan['restart_notice'],
                restart_reason=update_plan['restart_reason'],
                reboot_trigger_files=update_plan['reboot_trigger_files'],
            )
            stop_parent(args.parent_pid)
            time.sleep(1.0)
            reboot_system()
            return

        restart_message = 'Restarting DeckPilot to apply the update...'
        if update_plan['reboot_required'] is True and not update_plan['automatic_reboot_available']:
            restart_message = 'DeckPilot is restarting now. A manual Raspberry Pi reboot is still required after the update.'
        write_status(
            status_path,
            phase='restarting',
            step=3,
            detail=None,
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

        stop_parent(args.parent_pid)

        if not args.service_name:
            start_app(repo_root, args.python_executable, env)

        if not wait_for_http(args.port):
            raise RuntimeError('DeckPilot did not come back online after the update.')

        success_message = 'DeckPilot updated successfully.'
        if update_plan['reboot_required'] and not update_plan['automatic_reboot_available']:
            success_message = 'DeckPilot updated successfully. A manual Raspberry Pi reboot is still required.'
        elif update_plan.get('bootstrap_refresh_recommended'):
            success_message = (
                'DeckPilot updated successfully. System service definitions changed:'
                ' re-run scripts/bootstrap.sh once to apply them.'
            )
        write_status(
            status_path,
            phase='success',
            step=4,
            detail=None,
            message=success_message,
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
