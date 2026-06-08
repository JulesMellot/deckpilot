from __future__ import annotations

import platform
import subprocess
from pathlib import Path
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
        outputs = self._detect_linux_xrandr_outputs()
        if outputs:
            return outputs
        return self._detect_linux_drm_outputs()

    def _detect_linux_xrandr_outputs(self) -> List[VideoOutput]:
        active_monitors = self._detect_linux_xrandr_active_monitors()
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
            width, height = active_monitors.get(physical_name, (None, None))
            if width is None or height is None:
                for token in parts:
                    if 'x' in token and '+' in token:
                        resolution = token.split('+', 1)[0]
                        if 'x' in resolution:
                            w, h = resolution.split('x', 1)
                            width = int(w)
                            height = int(h)
                            break
            label = physical_name if width is None else f'{physical_name} ({width}x{height})'
            current_mode = f'{width}x{height}' if width and height else None
            outputs.append(VideoOutput(id=str(logical_index), label=label, width=width, height=height, primary=primary))
            outputs[-1].current_mode = current_mode
            if current_mode:
                outputs[-1].modes = [current_mode]
            logical_index += 1
        return outputs

    def _detect_linux_xrandr_active_monitors(self) -> dict[str, tuple[int | None, int | None]]:
        try:
            result = subprocess.run(['xrandr', '--listactivemonitors'], capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return {}
        monitors: dict[str, tuple[int | None, int | None]] = {}
        for line in result.stdout.splitlines():
            if ':' not in line or '+' not in line or '/' not in line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            geometry = parts[2]
            name = parts[3]
            size = geometry.split('+', 1)[0]
            if 'x' not in size:
                continue
            width_text, height_text = size.split('x', 1)
            try:
                width = int(width_text.split('/', 1)[0])
                height = int(height_text.split('/', 1)[0])
            except ValueError:
                continue
            monitors[name] = (width, height)
        return monitors

    def _detect_linux_drm_outputs(self) -> List[VideoOutput]:
        outputs: list[VideoOutput] = []
        status_files = sorted(Path('/sys/class/drm').glob('card*-*/status'))
        primary_assigned = False
        for status_file in status_files:
            try:
                status = status_file.read_text(encoding='utf-8').strip().lower()
            except OSError:
                continue
            if status != 'connected':
                continue

            connector_dir = status_file.parent
            connector_key = connector_dir.name
            if '-' not in connector_key:
                continue
            card_name, connector_name = connector_key.split('-', 1)
            active_mode_file = connector_dir / 'mode'
            mode_file = connector_dir / 'modes'
            width = height = None
            refresh_hz = None
            current_mode = None
            available_modes: list[str] = []
            label = connector_name
            mode_value = ''
            if active_mode_file.exists():
                try:
                    mode_value = active_mode_file.read_text(encoding='utf-8').strip()
                except OSError:
                    mode_value = ''
            if mode_file.exists():
                try:
                    available_modes = [line.strip() for line in mode_file.read_text(encoding='utf-8').splitlines() if line.strip()]
                except OSError:
                    available_modes = []
            if not mode_value and mode_file.exists():
                try:
                    mode_value = next((line.strip() for line in mode_file.read_text(encoding='utf-8').splitlines() if line.strip()), '')
                except OSError:
                    mode_value = ''
            if mode_value and 'x' in mode_value:
                mode_part = mode_value
                current_mode = mode_value
                if '@' in mode_part:
                    resolution, hz = mode_part.split('@', 1)
                    try:
                        refresh_hz = float(hz)
                    except ValueError:
                        refresh_hz = None
                else:
                    resolution = mode_part
                try:
                    w, h = resolution.split('x', 1)
                    width = int(w)
                    height = int(h)
                except ValueError:
                    width = height = None
            if width and height:
                label = f'{connector_name} ({width}x{height})'

            outputs.append(
                VideoOutput(
                    id=f'drm:{card_name}.{connector_name}',
                    label=label,
                    width=width,
                    height=height,
                    refresh_hz=refresh_hz,
                    current_mode=current_mode,
                    modes=available_modes,
                    primary=not primary_assigned,
                )
            )
            primary_assigned = True
        return outputs

    def _detect_macos_outputs(self) -> List[VideoOutput]:
        return [VideoOutput(id='1', label='Main Display', primary=True)]

    def _detect_windows_outputs(self) -> List[VideoOutput]:
        return [VideoOutput(id='1', label='Display 1', primary=True)]
