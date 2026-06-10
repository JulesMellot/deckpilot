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
    # Values may themselves contain colons (timecodes); a new parameter only
    # starts at an alphabetic "key:" token.
    pattern = re.compile(r'([a-zA-Z ]+):\s*(.+?)(?=(?:\s+[a-zA-Z][a-zA-Z ]*:\s*)|$)')
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


# Official HyperDeck Ethernet Protocol failure codes (100-199).
FAIL_SYNTAX_ERROR = (100, 'syntax error')
FAIL_UNSUPPORTED_PARAMETER = (101, 'unsupported parameter')
FAIL_INVALID_VALUE = (102, 'invalid value')
FAIL_UNSUPPORTED = (103, 'unsupported')
FAIL_TIMELINE_EMPTY = (107, 'timeline empty')
FAIL_OUT_OF_RANGE = (109, 'out of range')
FAIL_REMOTE_DISABLED = (111, 'remote control disabled')
FAIL_CLIP_NOT_FOUND = (112, 'clip not found')
FAIL_INVALID_STATE = (150, 'invalid state')


def failure(code_and_name: tuple[int, str]) -> bytes:
    code, name = code_and_name
    return response(code, name)


def timecode_to_seconds(timecode: str, framerate: float) -> float | None:
    """Parse HH:MM:SS:FF (or +/- prefixed for relative moves) into seconds."""
    text = timecode.strip()
    sign = 1.0
    if text.startswith(('+', '-')):
        sign = -1.0 if text[0] == '-' else 1.0
        text = text[1:]
    parts = text.split(':')
    if len(parts) != 4:
        return None
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError:
        return None
    fps = max(framerate, 1.0)
    return sign * (hours * 3600 + minutes * 60 + seconds + frames / fps)
