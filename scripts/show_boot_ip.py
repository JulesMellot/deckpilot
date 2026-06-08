from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Display DeckPilot network info on the local HDMI console')
    parser.add_argument('--config', required=True, help='Path to DeckPilot config.json')
    parser.add_argument('--tty', default='/dev/tty1', help='Target TTY to render on')
    parser.add_argument('--refresh-seconds', type=float, default=5.0, help='Refresh interval in seconds')
    return parser.parse_args()


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def detect_ips() -> list[str]:
    candidates: set[str] = set()
    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
        candidates.update(ip for ip in ips if ip)
    except OSError:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        candidates.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass

    if shutil.which('hostname'):
        try:
            output = subprocess.run(
                ['hostname', '-I'],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if output.returncode == 0:
                candidates.update(ip for ip in output.stdout.split() if ip)
        except (OSError, subprocess.SubprocessError):
            pass

    if not candidates:
        candidates.add('127.0.0.1')

    return sorted(candidates)


def render_screen(config: dict, hostname: str, ips: list[str]) -> str:
    http_port = int(config.get('http_port', 8080) or 8080)
    hyperdeck_port = int(config.get('hyperdeck_port', 9993) or 9993)
    primary_ip = next((ip for ip in ips if not ip.startswith('127.')), ips[0] if ips else '127.0.0.1')
    http_url = f'http://{primary_ip}:{http_port}'
    hyperdeck_target = f'{primary_ip}:{hyperdeck_port}'
    all_ips = ', '.join(ips) if ips else '127.0.0.1'
    lines = [
        '\033[2J\033[H',
        '========================================',
        '              DECKPILOT',
        '========================================',
        '',
        f'Hostname:   {hostname}',
        f'Primary IP: {primary_ip}',
        f'All IPs:    {all_ips}',
        '',
        f'Web UI:     {http_url}',
        f'HyperDeck:  {hyperdeck_target}',
        '',
        'Tip: open the Web UI from another device',
        'on the same network to control DeckPilot.',
        '',
        f'Updated: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        '',
    ]
    return '\n'.join(lines)


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    tty_path = Path(args.tty)
    refresh_seconds = max(1.0, float(args.refresh_seconds))

    try:
        tty = tty_path.open('w', encoding='utf-8', buffering=1)
    except OSError as exc:
        print(f'Failed to open {tty_path}: {exc}', file=sys.stderr)
        return 1

    hostname = socket.gethostname()

    try:
        while True:
            config = load_config(config_path)
            payload = render_screen(config, hostname, detect_ips())
            tty.write(payload)
            tty.flush()
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        tty.close()


if __name__ == '__main__':
    raise SystemExit(main())
