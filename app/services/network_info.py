from __future__ import annotations

import socket
from typing import List


class NetworkInfoService:
    def __init__(self, http_port: int, hyperdeck_port: int) -> None:
        self.http_port = http_port
        self.hyperdeck_port = hyperdeck_port

    async def snapshot(self) -> dict:
        ips = self._detect_ips()
        primary_ip = next((ip for ip in ips if not ip.startswith('127.')), '127.0.0.1')
        return {
            'hostname': socket.gethostname(),
            'primary_ip': primary_ip,
            'ips': ips,
            'http_port': self.http_port,
            'hyperdeck_port': self.hyperdeck_port,
            'http_url': f'http://{primary_ip}:{self.http_port}',
            'hyperdeck_target': f'{primary_ip}:{self.hyperdeck_port}',
        }

    def _detect_ips(self) -> List[str]:
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
        if not candidates:
            candidates.add('127.0.0.1')
        return sorted(candidates)
