"""Golden-file regression test for the decomposer.

Loads the fixture plan at ``tests/fixtures/decompose_golden_plan.md`` and
asserts that ``decompose_plan_phase`` produces an artifact byte-equal to the
canonical snapshot at ``tests/fixtures/decompose_golden_expected.json`` for
every phase id declared in the fixture.

The fixture exercises every parser path:
- Phase 1: em-dash heading + bold complexity tag, full Files-to-create
  section, ``### Acceptance criteria`` with 4 bullets, ``### Verification
  commands`` with a 2-line bash fence.
- Phase 2: simple heading without complexity tag, has File Targets but no
  Verification section.
- Phase 3: NO File Targets section, plenty of inline backticks referencing
  fake paths plus stoplist tokens (``accept/reject`` etc.) which must NOT
  bleed into ``allowed_files``.
- Phase 4: heading uses em-dash, has File Targets table with 11 entries,
  validation fence references ``docs/swarmdaddy-prepare-gate-plan.md`` which
  must NOT be captured.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from swarm_do.pipeline.decompose import decompose_plan_phase

FIXTURE_DIR = Path(__file__).parent / "fixtures"
PLAN_PATH = FIXTURE_DIR / "decompose_golden_plan.md"
EXPECTED_PATH = FIXTURE_DIR / "decompose_golden_expected.json"


def _canonicalize(artifact: dict) -> dict:
    """Normalize the artifact for byte-equal comparison.

    ``decompose_plan_phase`` writes the absolute fixture path into
    ``plan_path``; we replace it with a stable relative form so the snapshot
    can be checked into the repo and re-run anywhere.
    """

    canonical = json.loads(json.dumps(artifact, sort_keys=True))
    canonical["plan_path"] = "tests/fixtures/decompose_golden_plan.md"
    return canonical


class DecomposeGoldenTests(unittest.TestCase):
    def test_artifact_matches_snapshot(self) -> None:
        expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
        for phase_id in sorted(expected):
            with self.subTest(phase=phase_id):
                result = decompose_plan_phase(PLAN_PATH, phase_id)
                actual_canonical = _canonicalize(result.artifact)
                expected_canonical = expected[phase_id]
                actual_json = json.dumps(actual_canonical, indent=2, sort_keys=True)
                expected_json = json.dumps(expected_canonical, indent=2, sort_keys=True)
                self.assertEqual(actual_json, expected_json)

    def test_phase_3_has_no_referenced_file_leakage(self) -> None:
        """Stoplist tokens like ``accept/reject`` must not enter allowed_files."""

        result = decompose_plan_phase(PLAN_PATH, "3")
        for unit in result.artifact["work_units"]:
            for path in unit["allowed_files"]:
                self.assertNotIn("accept/reject", path)
                self.assertNotIn("read/write", path)
                self.assertNotIn("inspect/decompose", path)

    def test_phase_4_fence_paths_do_not_leak(self) -> None:
        """Paths inside ``### Verification commands`` fences are reference-only."""

        result = decompose_plan_phase(PLAN_PATH, "4")
        all_files = {
            path
            for unit in result.artifact["work_units"]
            for path in unit["allowed_files"]
        }
        self.assertNotIn("docs/swarmdaddy-prepare-gate-plan.md", all_files)


if __name__ == "__main__":
    unittest.main()
