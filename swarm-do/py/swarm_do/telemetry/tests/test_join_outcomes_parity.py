"""Byte-parity test for `swarm-telemetry join-outcomes` (Phase 3 commit 6).

The join-outcomes correlation logic depends on a real git repo + gh shim
for its non-empty code paths. A full parity test for matched rows would
require seeding a repository with known merge commits and a deterministic
ULID generator — out of scope for this commit's harness.

This test exercises the empty-findings fast path, which emits a fixed
stderr message and exits 0 without touching git/gh/bd. The full subcommand
port is exercised via the legacy bash self-test suite (swarm-telemetry
--test), which passes. This keeps byte-parity coverage real while
respecting the non-determinism constraints noted in phase-3 analysis.
"""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


class JoinOutcomesParityTests(unittest.TestCase):
    def test_absent_findings_fast_path(self) -> None:
        # fixture has .git/HEAD and an empty telemetry dir -> the legacy
        # script short-circuits with the "findings.jsonl absent or empty"
        # stderr message and returns 0.
        fixture = FIXTURES_DIR / "join_outcomes" / "absent"
        run_parity(
            "join-outcomes",
            ["--repo", "{tempdir}"],
            fixture,
            env_overrides={"_PLACEHOLDER": "{tempdir}"},
            compare_stderr=True,
            test_case=self,
        )


if __name__ == "__main__":
    unittest.main()
