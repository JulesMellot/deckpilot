import json
import os
import sys
from pathlib import Path

import pytest

from app.services.update_runner import run_streaming


def _read_status(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_run_streaming_mirrors_output_into_status(tmp_path):
    status = tmp_path / 'status.json'
    # Print a line, linger long enough for the 1 s poll loop to see it.
    script = "import sys,time; print('Collecting example-package'); sys.stdout.flush(); time.sleep(1.6)"
    run_streaming([sys.executable, '-c', script], tmp_path, dict(os.environ), status, timeout=30)
    assert _read_status(status)['detail'] == 'Collecting example-package'


def test_run_streaming_raises_with_output_tail_on_failure(tmp_path):
    status = tmp_path / 'status.json'
    script = "import sys; print('resolving deps'); print('ERROR: no matching distribution'); sys.exit(1)"
    with pytest.raises(RuntimeError) as excinfo:
        run_streaming([sys.executable, '-c', script], tmp_path, dict(os.environ), status, timeout=30)
    assert 'no matching distribution' in str(excinfo.value)


def test_run_streaming_kills_silent_hang(tmp_path):
    status = tmp_path / 'status.json'
    script = "import time; time.sleep(30)"
    with pytest.raises(RuntimeError) as excinfo:
        run_streaming([sys.executable, '-c', script], tmp_path, dict(os.environ), status, timeout=1)
    assert 'timed out' in str(excinfo.value)
