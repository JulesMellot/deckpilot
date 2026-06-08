from __future__ import annotations

import re
from typing import Dict, Tuple


def parse_command(line: str) -> Tuple[str, Dict[str, str]]:
    line = line.strip()
    if not line:
        return '', {}
    if ':' not in line:
        return line.lower(), {}
    command, rest = line.split(':', 1)
    params: dict[str, str] = {}
    pattern = re.compile(r'([a-zA-Z ]+):\s*([^:]+?)(?=(?:\s+[a-zA-Z ]+:\s*)|$)')
    for match in pattern.finditer(rest):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        params[key] = value
    return command.strip().lower(), params


def boolish(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {'true', 'yes', '1', 'on'}


def response(code: int, title: str, *lines: str) -> bytes:
    payload = [f'{code} {title}']
    payload.extend(lines)
    return ('\r\n'.join(payload) + '\r\n\r\n').encode('utf-8')


def ok() -> bytes:
    return response(200, 'ok')


def error(message: str) -> bytes:
    return response(400, 'error', f'message: {message}')
