from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

THERMAL_PATH = Path('/sys/class/thermal/thermal_zone0/temp')
MEMINFO_PATH = Path('/proc/meminfo')


def read_system_vitals() -> Dict[str, Any]:
    """Cheap host vitals for the operator panel (procfs/sysfs reads only).

    Values are rounded coarsely on purpose: the health broadcast is
    change-deduplicated, so noisy decimals would defeat the dedup.
    """
    vitals: Dict[str, Any] = {}
    try:
        vitals['load_1m'] = round(os.getloadavg()[0], 1)
    except (OSError, AttributeError):
        pass
    try:
        vitals['cpu_temp_c'] = int(int(THERMAL_PATH.read_text().strip()) / 1000)
    except (OSError, ValueError):
        pass
    try:
        total_kb = available_kb = None
        for line in MEMINFO_PATH.read_text().splitlines():
            if line.startswith('MemTotal:'):
                total_kb = int(line.split()[1])
            elif line.startswith('MemAvailable:'):
                available_kb = int(line.split()[1])
            if total_kb is not None and available_kb is not None:
                break
        if total_kb and available_kb is not None:
            vitals['mem_used_percent'] = int(round((total_kb - available_kb) * 100 / total_kb))
    except (OSError, ValueError, IndexError):
        pass
    return vitals
