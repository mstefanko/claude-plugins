"""Byte-parity test for `swarm-telemetry validate` (Phase 3 commit 2).

Validate emits no stdout — all output is informational stderr. The parity
harness therefore compares BOTH stdout and stderr plus exit codes.
Error messages, 3-per-row cap, and min(fail_count, 255) per-ledger
accumulation are tested via a mixed-failure fixture.
"""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


_GOLDEN = FIXTURES_DIR / "validate" / "golden"


class ValidateParityTests(unittest.TestCase):
    def test_validate_mixed_finding_outcomes(self) -> None:
        # All five failure shapes: valid row, missing required, bad pattern,
        # JSON parse error, bad enum. Exit code is 1 (total_fail > 0).
        run_parity(
            "validate",
            ["finding_outcomes"],
            FIXTURES_DIR / "validate" / "mixed",
            compare_stderr=True,
            test_case=self,
            golden_stdout_path=_GOLDEN / "mixed_finding_outcomes.stdout",
            golden_stderr_path=_GOLDEN / "mixed_finding_outcomes.stderr",
            golden_exit_path=_GOLDEN / "mixed_finding_outcomes.exit",
            normalize_tempdir=True,
        )

    def test_validate_all_absent(self) -> None:
        # Every ledger absent -> 5 "ledger absent" lines + "all ledgers OK".
        run_parity(
            "validate",
            [],
            FIXTURES_DIR / "validate" / "all_absent",
            compare_stderr=True,
            test_case=self,
            golden_stdout_path=_GOLDEN / "all_absent.stdout",
            golden_stderr_path=_GOLDEN / "all_absent.stderr",
            golden_exit_path=_GOLDEN / "all_absent.exit",
            normalize_tempdir=True,
        )

    def test_validate_all_in_mixed_fixture(self) -> None:
        # No argument: legacy iterates all 5 ledgers in fixed order; only
        # finding_outcomes has rows, others log absent.
        run_parity(
            "validate",
            [],
            FIXTURES_DIR / "validate" / "mixed",
            compare_stderr=True,
            test_case=self,
            golden_stdout_path=_GOLDEN / "all_mixed.stdout",
            golden_stderr_path=_GOLDEN / "all_mixed.stderr",
            golden_exit_path=_GOLDEN / "all_mixed.exit",
            normalize_tempdir=True,
        )


if __name__ == "__main__":
    unittest.main()
