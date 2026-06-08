from __future__ import annotations

import platform
import subprocess
from typing import List

from app.core.models import VideoOutput


class OutputManager:
    def __init__(self) -> None:
        self.platform_name = platform.system().lower()
        self._selected_output_id: str | None = None

    async def initialize(self) -> None:
        outputs = await self.list_outputs()
        if outputs and self._selected_output_id is None:
            preferred = next((item for item in outputs if item.primary), outputs[0])
            self._selected_output_id = preferred.id

    async def list_outputs(self) -> List[VideoOutput]:
        outputs: list[VideoOutput] = []
        if self.platform_name == 'darwin':
            outputs = self._detect_macos_outputs()
        elif self.platform_name == 'linux':
            outputs = self._detect_linux_outputs()
        elif self.platform_name == 'windows':
            outputs = self._detect_windows_outputs()
        if not outputs:
            outputs = [VideoOutput(id='default', label='Default Display', primary=True)]
        for output in outputs:
            output.selected = output.id == self._selected_output_id
        return outputs

    async def set_selected_output(self, output_id: str) -> str:
        self._selected_output_id = output_id
        return output_id

    async def get_selected_output(self) -> VideoOutput | None:
        outputs = await self.list_outputs()
        return next((item for item in outputs if item.selected), None)

    def _detect_linux_outputs(self) -> List[VideoOutput]:
        try:
            result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return []
        outputs: list[VideoOutput] = []
        logical_index = 1
        for line in result.stdout.splitlines():
            if ' connected' not in line:
                continue
            parts = line.split()
            physical_name = parts[0]
            primary = 'primary' in parts
            width = height = None
            for token in parts:
                if 'x' in token and '+' in token:
                    resolution = token.split('+', 1)[0]
                    if 'x' in resolution:
                        w, h = resolution.split('x', 1)
                        width = int(w)
                        height = int(h)
                        break
            label = physical_name if width is None else f'{physical_name} ({width}x{height})'
            outputs.append(VideoOutput(id=str(logical_index), label=label, width=width, height=height, primary=primary))
            logical_index += 1
        return outputs

    def _detect_macos_outputs(self) -> List[VideoOutput]:
        return [VideoOutput(id='1', label='Main Display', primary=True)]

    def _detect_windows_outputs(self) -> List[VideoOutput]:
        return [VideoOutput(id='1', label='Display 1', primary=True)]
