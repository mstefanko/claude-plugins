"""Byte-parity test for `swarm-telemetry dump` (Phase 3 commit 1)."""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


class DumpParityTests(unittest.TestCase):
    def test_dump_runs_populated(self) -> None:
        run_parity(
            "dump",
            ["runs"],
            FIXTURES_DIR / "dump" / "populated",
            test_case=self,
        )

    def test_dump_runs_empty(self) -> None:
        run_parity(
            "dump",
            ["runs"],
            FIXTURES_DIR / "dump" / "empty",
            test_case=self,
        )


if __name__ == "__main__":
    unittest.main()
