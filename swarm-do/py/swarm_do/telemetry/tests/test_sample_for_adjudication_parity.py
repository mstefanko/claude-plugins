"""Byte-parity test for `swarm-telemetry sample-for-adjudication` (Phase 3 commit 5).

Fixture stratifies 1 finding per stratum so allocation (floor-1 proportional)
produces exactly 1 finding per stratum → deterministic count. Stdout's 3
summary lines only depend on len(sampled), output_root, rubric_version, and
batch_id — all deterministic with SWARM_TELEMETRY_NOW + SWARM_PHASE0_ROOT.
"""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


FIXTURE = FIXTURES_DIR / "sample_for_adjudication" / "populated"
_GOLDEN = FIXTURES_DIR / "sample_for_adjudication" / "golden"
ENV = {
    "SWARM_TELEMETRY_NOW": "2026-04-24T00:00:00Z",
    "SWARM_PHASE0_ROOT": "{tempdir}/_sfa_out",
}


class SampleForAdjudicationParityTests(unittest.TestCase):
    def test_count_3_all_strata(self) -> None:
        # 3 non-adjudicated findings across 3 strata -> 1 per stratum.
        run_parity(
            "sample-for-adjudication",
            ["--count", "3"],
            FIXTURE,
            env_overrides=ENV,
            test_case=self,
            golden_stdout_path=_GOLDEN / "count_3_all_strata.stdout",
            normalize_tempdir=True,
        )

    def test_count_3_with_since_excludes_old(self) -> None:
        # --since 2d excludes findings older than 2d from 2026-04-24.
        run_parity(
            "sample-for-adjudication",
            ["--count", "3", "--since", "2d"],
            FIXTURE,
            env_overrides=ENV,
            test_case=self,
            golden_stdout_path=_GOLDEN / "count_3_since_2d.stdout",
            normalize_tempdir=True,
        )


if __name__ == "__main__":
    unittest.main()
