#!/usr/bin/env python3
"""HyperDeck protocol test bench.

Talks the Blackmagic HyperDeck Ethernet Protocol to any deck — DeckPilot or
real hardware — with a proper protocol parser (no sleep-and-hope), and three
tools in one:

  interactive REPL    raw commands + operator aliases, async events inline
  --check             spec-conformance suite (safe by default, read-only)
  --monitor           subscribe to notifications and stream them live
  --send "cmd" ...    scripted batch mode

Pure standard library. Examples:

  python3 scripts/hyperdeck_test_client.py 192.168.1.40
  python3 scripts/hyperdeck_test_client.py 192.168.1.40 --check
  python3 scripts/hyperdeck_test_client.py 192.168.1.40 --check --allow-transport
  python3 scripts/hyperdeck_test_client.py 192.168.1.40 --monitor
  python3 scripts/hyperdeck_test_client.py --send "device info" "clips get"
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import socket
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Terminal styling
# ---------------------------------------------------------------------------

IS_TTY = sys.stdout.isatty()
USE_COLOR = IS_TTY and not os.environ.get('NO_COLOR') and os.environ.get('TERM') != 'dumb'


def _c(code: str) -> str:
    return f'\033[{code}m' if USE_COLOR else ''


RESET = _c('0')
BOLD = _c('1')
DIM = _c('2')
RED = _c('31')
GREEN = _c('32')
YELLOW = _c('33')
BLUE = _c('34')
MAGENTA = _c('35')
CYAN = _c('36')

UTF8_OK = 'UTF-8' in (os.environ.get('LC_ALL') or os.environ.get('LANG') or '').upper().replace('UTF8', 'UTF-8')
SYM_OK = '✔' if UTF8_OK else 'OK'
SYM_FAIL = '✖' if UTF8_OK else 'XX'
SYM_EVENT = '⚡' if UTF8_OK else '**'
SYM_SEND = '→' if UTF8_OK else '>>'
SYM_RECV = '←' if UTF8_OK else '<<'


def banner(host: str, port: int, mode: str) -> None:
    line = '─' if UTF8_OK else '-'
    print()
    print(f'{DIM}{"╭" if UTF8_OK else "+"}{line * 56}{"╮" if UTF8_OK else "+"}{RESET}')
    print(f'{DIM}{"│" if UTF8_OK else "|"}{RESET}  {BOLD}{CYAN}HYPERDECK TEST BENCH{RESET}  {DIM}{host}:{port}  [{mode}]{RESET}')
    print(f'{DIM}{"╰" if UTF8_OK else "+"}{line * 56}{"╯" if UTF8_OK else "+"}{RESET}')
    print()


def code_color(code: int) -> str:
    if 100 <= code < 200:
        return RED
    if 200 <= code < 300:
        return GREEN
    if 500 <= code < 600:
        return MAGENTA
    return YELLOW


def print_block(block: list[str], prefix: str = SYM_RECV, is_async: bool = False) -> None:
    code = block_code(block)
    color = code_color(code)
    marker = f'{MAGENTA}{SYM_EVENT}{RESET}' if is_async else f'{DIM}{prefix}{RESET}'
    stamp = f'{DIM}{time.strftime("%H:%M:%S")}{RESET} ' if is_async else ''
    print(f'  {stamp}{marker} {color}{block[0]}{RESET}')
    for line in block[1:]:
        print(f'      {DIM}{line}{RESET}')


# ---------------------------------------------------------------------------
# Protocol client
# ---------------------------------------------------------------------------


def block_code(block: list[str]) -> int:
    try:
        return int(block[0].split(' ', 1)[0])
    except (ValueError, IndexError):
        return 0


def block_params(block: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for line in block[1:]:
        if ':' in line:
            key, value = line.split(':', 1)
            params[key.strip().lower()] = value.strip()
    return params


class DeckClient:
    """Spec-correct protocol reader: single-line replies, parameter blocks
    terminated by a blank line, and 5xx asynchronous messages routed apart."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.greeting: list[str] | None = None
        self.responses: queue.Queue[list[str]] = queue.Queue()
        self.async_handler = None  # callable(block) or None to buffer
        self.async_buffer: list[list[str]] = []
        self.connected = False
        self._reader: threading.Thread | None = None

    def connect(self, timeout: float = 4.0) -> list[str]:
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(None)
        self.connected = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        deadline = time.monotonic() + timeout
        while self.greeting is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.greeting is None:
            raise ConnectionError('no greeting received (is this a HyperDeck port?)')
        return self.greeting

    def close(self) -> None:
        self.connected = False
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def send(self, command: str, timeout: float = 3.0) -> list[str] | None:
        assert self.sock is not None
        self.sock.sendall((command + '\r\n').encode('utf-8'))
        try:
            return self.responses.get(timeout=timeout)
        except queue.Empty:
            return None

    def _read_loop(self) -> None:
        assert self.sock is not None
        stream = self.sock.makefile('r', encoding='utf-8', errors='replace', newline='\n')
        try:
            while self.connected:
                block = self._read_block(stream)
                if block is None:
                    break
                code = block_code(block)
                if self.greeting is None and code == 500:
                    self.greeting = block
                elif 500 <= code < 600:
                    handler = self.async_handler
                    if handler is not None:
                        handler(block)
                    else:
                        self.async_buffer.append(block)
                else:
                    self.responses.put(block)
        except (OSError, ValueError):
            pass
        finally:
            self.connected = False

    @staticmethod
    def _read_block(stream) -> list[str] | None:
        # Skip blank separators, then read one response block.
        while True:
            line = stream.readline()
            if not line:
                return None
            line = line.rstrip('\r\n')
            if line:
                break
        block = [line]
        if line.endswith(':'):
            while True:
                line = stream.readline()
                if not line:
                    break
                line = line.rstrip('\r\n')
                if not line:
                    break
                block.append(line)
        return block


# ---------------------------------------------------------------------------
# Conformance suite (built from the official Ethernet Protocol document)
# ---------------------------------------------------------------------------

TIMECODE_RE = r'\d{2}:\d{2}:\d{2}[:;]\d{2}'
CLIP_LINE_RE = re.compile(rf'^\d+: .+ {TIMECODE_RE} {TIMECODE_RE}$')


class Conformance:
    def __init__(self, client: DeckClient, allow_transport: bool) -> None:
        self.client = client
        self.allow_transport = allow_transport
        self.results: list[tuple[bool, str, str]] = []

    def check(self, name: str, passed: bool, detail: str = '') -> None:
        self.results.append((passed, name, detail))
        symbol = f'{GREEN}{SYM_OK}{RESET}' if passed else f'{RED}{SYM_FAIL}{RESET}'
        suffix = f'  {DIM}{detail}{RESET}' if detail else ''
        print(f'  {symbol} {name}{suffix}')

    def expect(self, name: str, command: str, code: int, required: list[str] | None = None) -> list[str] | None:
        block = self.client.send(command)
        if block is None:
            self.check(name, False, f'`{command}` got no response')
            return None
        got = block_code(block)
        if got != code:
            self.check(name, False, f'`{command}` answered {block[0]!r}, expected {code}')
            return block
        missing = [key for key in (required or []) if key not in block_params(block)]
        if missing:
            self.check(name, False, f'missing parameter(s): {", ".join(missing)}')
            return block
        self.check(name, True, f'{code} with {len(block) - 1} parameter(s)' if required else str(code))
        return block

    def expect_failure(self, name: str, command: str, ideal: int) -> None:
        block = self.client.send(command)
        if block is None:
            self.check(name, False, f'`{command}` got no response')
            return
        got = block_code(block)
        if 100 <= got < 200:
            note = '' if got == ideal else f'got {got}, spec suggests {ideal}'
            self.check(name, True, note or str(got))
        else:
            self.check(name, False, f'`{command}` answered {block[0]!r}, expected a 1xx failure')

    def run(self) -> bool:
        print(f'{BOLD}Connection{RESET}')
        greeting = self.client.greeting or []
        self.check('greeting is `500 connection info:`', block_code(greeting) == 500)
        params = block_params(greeting)
        self.check('greeting carries protocol version + model',
                   'protocol version' in params and 'model' in params,
                   f'protocol {params.get("protocol version", "?")} / {params.get("model", "?")}')

        print(f'\n{BOLD}Identity{RESET}')
        self.expect('ping', 'ping', 200)
        block = self.expect('device info', 'device info', 204, ['protocol version', 'model'])
        if block is not None and block_code(block) == 204:
            extras = block_params(block)
            self.check('device info includes slot count + software version',
                       'slot count' in extras and 'software version' in extras)
        self.expect('configuration', 'configuration', 211)

        print(f'\n{BOLD}Media{RESET}')
        block = self.client.send('clips get')
        if block is None or block_code(block) != 205:
            self.check('clips get answers 205 clips info:', False,
                       'no response' if block is None else repr(block[0]))
        else:
            self.check('clips get answers 205 clips info:', True)
            clip_lines = [line for line in block[1:] if re.match(r'^\d+:', line)]
            bad = [line for line in clip_lines if not CLIP_LINE_RE.match(line)]
            self.check('clip lines follow `{id}: {name} {start} {duration}`',
                       not bad, bad[0] if bad else f'{len(clip_lines)} clip(s)')
        self.expect('slot info', 'slot info', 202, ['slot id', 'status'])
        self.expect_failure('invalid slot select fails with 1xx', 'slot select: slot id: 99', 102)

        print(f'\n{BOLD}Transport state{RESET}')
        block = self.expect('transport info', 'transport info', 208,
                            ['status', 'speed', 'slot id', 'clip id', 'display timecode', 'timecode'])
        if block is not None and block_code(block) == 208:
            extras = block_params(block)
            self.check('transport info includes single clip + loop',
                       'single clip' in extras and 'loop' in extras)

        print(f'\n{BOLD}Sessions & notifications{RESET}')
        self.expect('remote info answers 210 with enabled + override', 'remote info', 210, ['enabled', 'override'])
        block = self.expect('bare `notify` query answers 209 with flags', 'notify', 209, ['transport'])
        before = block_params(block or []).get('transport')
        self.check('notifications are disabled by default', before == 'false', f'transport: {before}')
        self.expect('notify set transport', 'notify: transport: true', 200)
        block = self.client.send('notify')
        self.check('notify set is reflected by the query',
                   block is not None and block_params(block).get('transport') == 'true')
        self.client.send('notify: transport: false')

        print(f'\n{BOLD}Error handling{RESET}')
        self.expect_failure('unknown command fails with 100 syntax error', 'deckpilot conformance probe', 100)
        self.expect_failure('goto without parameters fails cleanly', 'goto', 100)

        if self.allow_transport:
            print(f'\n{BOLD}Transport actions{RESET} {DIM}(--allow-transport){RESET}')
            self.expect_failure('goto unknown clip fails with 112', 'goto: clip id: 9999', 112)
            block = self.client.send('goto: clip id: 1')
            self.check('goto first clip', block is not None and block_code(block) == 200,
                       repr(block[0]) if block else 'no response')
            block = self.client.send('goto: clip id: +1')
            if block is not None and block_code(block) == 200:
                info = self.client.send('transport info')
                clip_id = block_params(info or []).get('clip id')
                self.check('relative `goto: clip id: +1` moved to clip 2', clip_id == '2', f'clip id: {clip_id}')
            else:
                self.check('relative `goto: clip id: +1` accepted', False,
                           repr(block[0]) if block else 'no response')
            self.expect_failure('invalid play speed fails with 102', 'play: speed: garbage', 102)
            self.expect('stop', 'stop', 200)
        else:
            print(f'\n  {DIM}{SYM_EVENT} transport actions skipped (re-run with --allow-transport){RESET}')

        passed = sum(1 for ok_flag, _, _ in self.results if ok_flag)
        total = len(self.results)
        all_ok = passed == total
        color = GREEN if all_ok else (YELLOW if passed >= total - 2 else RED)
        print(f'\n{BOLD}{color}{"PASS" if all_ok else "ISSUES"}{RESET}  {passed}/{total} checks passed', end='')
        if self.client.async_buffer:
            print(f'  {DIM}({len(self.client.async_buffer)} async event(s) observed){RESET}', end='')
        print('\n')
        for ok_flag, name, detail in self.results:
            if not ok_flag:
                print(f'  {RED}{SYM_FAIL}{RESET} {name}{f"  {DIM}{detail}{RESET}" if detail else ""}')
        return all_ok


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

ALIASES_HELP = [
    ('p, play [pct]', 'play (optionally `play 50` for speed)'),
    ('s, stop', 'stop'),
    ('n / b', 'next / previous clip (relative goto)'),
    ('cue N', 'goto: clip id: N'),
    ('tc HH:MM:SS:FF', 'goto: timecode: ...'),
    ('ti', 'transport info'),
    ('clips', 'clips get'),
    ('sub / unsub', 'enable / disable all notifications'),
    ('check', 'run the conformance suite (read-only)'),
    ('?', 'this help — anything else is sent raw'),
    ('q', 'quit'),
]


def expand_alias(line: str) -> str | None:
    parts = line.split()
    head = parts[0].lower()
    rest = parts[1:]
    if head in ('p', 'play'):
        return f'play: speed: {rest[0]}' if rest else 'play'
    if head in ('s', 'stop'):
        return 'stop'
    if head == 'n':
        return 'goto: clip id: +1'
    if head == 'b':
        return 'goto: clip id: -1'
    if head == 'cue' and rest:
        return f'goto: clip id: {rest[0]}'
    if head == 'tc' and rest:
        return f'goto: timecode: {rest[0]}'
    if head == 'ti':
        return 'transport info'
    if head == 'clips':
        return 'clips get'
    if head == 'sub':
        return 'notify: transport: true slot: true remote: true clips: true'
    if head == 'unsub':
        return 'notify: transport: false slot: false remote: false clips: false'
    return None


def repl(client: DeckClient) -> None:
    try:
        import readline  # noqa: F401  (history + arrows when available)
    except ImportError:
        pass

    client.async_handler = lambda block: print_block(block, is_async=True)
    for block in client.async_buffer:
        print_block(block, is_async=True)
    client.async_buffer.clear()

    print(f'  {DIM}aliases: p/s/n/b/cue/tc/ti/clips/sub — `?` for help, `q` to quit{RESET}\n')
    while True:
        try:
            line = input(f'{CYAN}deck{RESET}{DIM}>{RESET} ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ('q', 'quit', 'exit'):
            client.send('quit', timeout=1.0)
            break
        if line == '?':
            print()
            for alias, meaning in ALIASES_HELP:
                print(f'  {CYAN}{alias:<16}{RESET}{DIM}{meaning}{RESET}')
            print()
            continue
        if line.lower() == 'check':
            Conformance(client, allow_transport=False).run()
            continue
        command = expand_alias(line) or line
        if command != line:
            print(f'  {DIM}{SYM_SEND} {command}{RESET}')
        block = client.send(command)
        if block is None:
            print(f'  {YELLOW}{SYM_FAIL} no response within 3s{RESET}')
        else:
            print_block(block)


# ---------------------------------------------------------------------------
# Monitor mode
# ---------------------------------------------------------------------------


def monitor(client: DeckClient) -> None:
    client.async_handler = lambda block: print_block(block, is_async=True)
    client.send('notify: transport: true slot: true remote: true clips: true')
    print(f'  {DIM}subscribed to transport/slot/remote/clips — Ctrl+C to stop{RESET}\n')
    try:
        while client.connected:
            time.sleep(0.2)
        print(f'  {YELLOW}connection closed by the deck{RESET}')
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description='HyperDeck Ethernet Protocol test bench (works on DeckPilot and real decks).')
    parser.add_argument('host', nargs='?', default='127.0.0.1', help='deck IP or hostname')
    parser.add_argument('port', nargs='?', type=int, default=9993, help='TCP port (9993)')
    parser.add_argument('--check', action='store_true', help='run the spec-conformance suite')
    parser.add_argument('--allow-transport', action='store_true', help='let --check cue/play/stop clips (touches the output!)')
    parser.add_argument('--monitor', action='store_true', help='subscribe to notifications and stream them')
    parser.add_argument('--send', nargs='+', metavar='CMD', help='send command(s) and exit')
    args = parser.parse_args()

    mode = 'check' if args.check else 'monitor' if args.monitor else 'batch' if args.send else 'repl'
    banner(args.host, args.port, mode)

    client = DeckClient(args.host, args.port)
    try:
        greeting = client.connect()
    except (OSError, ConnectionError) as exc:
        print(f'  {RED}{SYM_FAIL} cannot connect to {args.host}:{args.port} — {exc}{RESET}\n')
        return 2
    print_block(greeting)
    print()

    exit_code = 0
    try:
        if args.check:
            ok_flag = Conformance(client, allow_transport=args.allow_transport).run()
            exit_code = 0 if ok_flag else 1
        elif args.monitor:
            monitor(client)
        elif args.send:
            for command in args.send:
                print(f'  {DIM}{SYM_SEND} {command}{RESET}')
                block = client.send(command)
                if block is None:
                    print(f'  {YELLOW}{SYM_FAIL} no response within 3s{RESET}')
                    exit_code = 1
                else:
                    print_block(block)
            print()
        else:
            repl(client)
    except KeyboardInterrupt:
        print()
    finally:
        client.close()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
