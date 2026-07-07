from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.update_runner import run_streaming, stop_parent


class RunStreamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.status = self.tmp_path / 'status.json'
        self.addCleanup(self._tmp.cleanup)

    def _read_status(self) -> dict:
        return json.loads(self.status.read_text(encoding='utf-8'))

    def test_mirrors_output_into_status(self) -> None:
        # Print a line, linger long enough for the 1 s poll loop to see it.
        script = "import sys,time; print('Collecting example-package'); sys.stdout.flush(); time.sleep(1.6)"
        run_streaming([sys.executable, '-c', script], self.tmp_path, dict(os.environ), self.status, timeout=30)
        self.assertEqual(self._read_status()['detail'], 'Collecting example-package')

    def test_raises_with_output_tail_on_failure(self) -> None:
        script = "import sys; print('resolving deps'); print('ERROR: no matching distribution'); sys.exit(1)"
        with self.assertRaises(RuntimeError) as ctx:
            run_streaming([sys.executable, '-c', script], self.tmp_path, dict(os.environ), self.status, timeout=30)
        self.assertIn('no matching distribution', str(ctx.exception))

    def test_kills_silent_hang(self) -> None:
        script = "import time; time.sleep(30)"
        with self.assertRaises(RuntimeError) as ctx:
            run_streaming([sys.executable, '-c', script], self.tmp_path, dict(os.environ), self.status, timeout=1)
        self.assertIn('timed out', str(ctx.exception))


class StopParentTests(unittest.TestCase):
    def test_escalates_to_sigkill_when_sigterm_is_ignored(self) -> None:
        # Mimic uvicorn wedged in graceful shutdown: SIGTERM is ignored.
        script = "import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"
        proc = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE)
        try:
            proc.stdout.readline()  # handler installed
            stop_parent(proc.pid, term_timeout=1)
            self.assertIsNotNone(proc.wait(timeout=5))
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == '__main__':
    unittest.main()
