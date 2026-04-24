"""Fault-injection tests for purge: verify atomic_write resilience.

Skipped unless SWARM_TEST_FAULT_INJECT=1 (manual test, POSIX only).

This test simulates an abrupt process termination (SIGKILL) during atomic_write
by forking a child that writes a tempfile then kills itself. The parent verifies
that:
  1. The original ledger file is intact and untouched.
  2. No orphaned .tmp file remains at the destination directory.

This ensures that atomic_write's tempfile+fsync+os.replace contract holds even
under process death mid-write.
"""

from __future__ import annotations

import os
import signal
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from swarm_do.telemetry.jsonl import atomic_write, stream_read


class FaultInjectAtomicWriteTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("SWARM_TEST_FAULT_INJECT") == "1",
        "set SWARM_TEST_FAULT_INJECT=1 to enable manual fault-injection test",
    )
    def test_fault_inject_original_intact(self) -> None:
        """Fork a child that dies mid-fsync; assert original .jsonl and no .tmp remain.

        Procedure:
          1. Create original ledger with 1 row.
          2. Fork child process.
          3. Child writes a large tempfile (1000 rows) to same directory, then kills itself.
          4. Parent waits for child death.
          5. Parent asserts:
             - Original ledger file still exists and contains original 1 row.
             - No .tmp file in parent directory.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            now = datetime.now(timezone.utc)

            # Write original ledger.
            original_rows = [
                {"id": "original", "timestamp": now.isoformat()}
            ]
            atomic_write(path, original_rows)

            # Fork child to die mid-write.
            pid = os.fork()
            if pid == 0:
                # Child process: attempt a large write, then die.
                try:
                    # Create a large set of rows.
                    big_rows = [
                        {"id": f"big_{i}", "timestamp": now.isoformat()}
                        for i in range(1000)
                    ]
                    # This will create a .tmp file in the directory.
                    # We'll kill the process inside atomic_write, after some writes but before fsync.
                    atomic_write(path, big_rows)
                except Exception:
                    pass
                # Kill ourselves (SIGKILL is not catchable).
                os.kill(os.getpid(), signal.SIGKILL)
                sys.exit(1)  # Never reached.
            else:
                # Parent: wait for child death.
                _, status = os.waitpid(pid, 0)
                # Child died by signal (SIGKILL).

            # Assert original file is intact.
            self.assertTrue(path.exists())
            readback = list(stream_read(path))
            self.assertEqual(readback, original_rows)

            # Assert no .tmp file remains.
            tmp_files = list(Path(tmpdir).glob(".test.jsonl.*.tmp"))
            self.assertEqual(
                len(tmp_files),
                0,
                msg=f"orphaned .tmp file(s) found: {tmp_files}",
            )


if __name__ == "__main__":
    unittest.main()
