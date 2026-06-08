from __future__ import annotations

import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9993
COMMANDS = [
    'device info',
    'clips get',
    'transport info',
    'goto: clip id: 1',
    'play: single clip: true',
    'stop',
    'quit',
]


def recv_block(sock: socket.socket) -> str:
    sock.settimeout(1.0)
    chunks = []
    while True:
        data = sock.recv(4096)
        if not data:
            break
        chunks.append(data.decode('utf-8', errors='ignore'))
        if chunks[-1].endswith('\r\n\r\n'):
            break
    return ''.join(chunks)


def main() -> None:
    with socket.create_connection((HOST, PORT), timeout=3) as sock:
        print('CONNECTED TO', HOST, PORT)
        print(recv_block(sock))
        for command in COMMANDS:
            print('>>', command)
            sock.sendall((command + '\r\n').encode('utf-8'))
            time.sleep(0.25)
            print(recv_block(sock))


if __name__ == '__main__':
    main()
