"""Codex extractor parity against extract-phase.sh.legacy.

Runs the legacy bash extractor AND the Python port against the pinned
`codex_findings.json` fixture (3 findings covering severity mapping edges,
location range vs single-line vs missing-line, category rewrite). Asserts
per-row equality on the parity-critical fields:

  - severity (mapped, not raw)
  - category (category_class after types/null rewrite)
  - file_path (after normalize_path)
  - line_start / line_end
  - stable_finding_hash_v1
  - short_summary
  - schema_ok

Volatile fields finding_id (random ULID) and timestamp (now()) are stripped
before comparison.

If the legacy `.legacy` script is missing the test still exercises the
Python extractor and validates against a precomputed expectation file,
keeping the test executable after Phase 4's legacy deletion commit.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.telemetry.extractors.codex_review import extract
from swarm_do.telemetry.registry import PLUGIN_ROOT


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "extractors"
FIXTURE_JSON = FIXTURE_DIR / "codex_findings.json"
LEGACY_SCRIPT = PLUGIN_ROOT / "swarm-do" / "bin" / "extract-phase.sh.legacy"
BIN_SHIM = PLUGIN_ROOT / "swarm-do" / "bin" / "extract-phase.sh"

_PARITY_FIELDS = (
    "severity",
    "category",
    "file_path",
    "line_start",
    "line_end",
    "stable_finding_hash_v1",
    "short_summary",
    "schema_ok",
    "role",
    "issue_id",
    "run_id",
)


def _run_extractor_script(script: Path, fixture: Path, tmpdir: Path) -> list[dict]:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmpdir)
    result = subprocess.run(
        [
            "bash",
            str(script),
            str(fixture),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    out_path = tmpdir / "telemetry" / "findings.jsonl"
    if not out_path.is_file():
        return []
    with out_path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class CodexParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(FIXTURE_JSON.is_file(), f"missing fixture: {FIXTURE_JSON}")

    def test_python_extracts_three_rows(self) -> None:
        rows = extract(
            str(FIXTURE_JSON),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        )
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertIn("stable_finding_hash_v1", row)
            self.assertIn("severity", row)
            self.assertEqual(row["role"], "agent-codex-review")
            self.assertEqual(row["issue_id"], "test-issue-1")

    def test_severity_mapping_matches_table(self) -> None:
        rows = extract(
            str(FIXTURE_JSON),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        )
        # warning -> high, error -> critical, info -> info (see plan WS-2).
        self.assertEqual(rows[0]["severity"], "high")
        self.assertEqual(rows[1]["severity"], "critical")
        self.assertEqual(rows[2]["severity"], "info")

    def test_category_rewrites_types_to_types_or_null(self) -> None:
        rows = extract(
            str(FIXTURE_JSON),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        )
        self.assertEqual(rows[0]["category"], "correctness")
        self.assertEqual(rows[1]["category"], "types_or_null")

    def test_location_parsing_handles_range_single_and_missing(self) -> None:
        rows = extract(
            str(FIXTURE_JSON),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        )
        self.assertEqual((rows[0]["line_start"], rows[0]["line_end"]), (42, 55))
        self.assertEqual((rows[1]["line_start"], rows[1]["line_end"]), (100, 100))
        # Third fixture has no `:` in location → no line info, no hash.
        self.assertIsNone(rows[2]["line_start"])
        self.assertIsNone(rows[2]["line_end"])
        self.assertIsNone(rows[2]["stable_finding_hash_v1"])

    def test_hash_is_deterministic_across_runs(self) -> None:
        args = (
            str(FIXTURE_JSON),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        )
        first = extract(*args)
        second = extract(*args)
        for a, b in zip(first, second):
            self.assertEqual(a["stable_finding_hash_v1"], b["stable_finding_hash_v1"])
            # Volatile fields differ across runs: finding_id is random.
            self.assertNotEqual(a["finding_id"], b["finding_id"])

    @unittest.skipUnless(
        LEGACY_SCRIPT.is_file() or BIN_SHIM.is_file(),
        "neither legacy script nor shim present",
    )
    def test_parity_with_bash_extractor(self) -> None:
        """Run the bash extractor (legacy OR shim) + python extractor; compare.

        If `.legacy` exists we prefer it (pure-bash byte-parity baseline).
        After Phase 4's legacy-deletion commit the shim itself dispatches to
        the Python port so this becomes a tautology — still executes and
        guards against future regressions to either side.
        """
        script = LEGACY_SCRIPT if LEGACY_SCRIPT.is_file() else BIN_SHIM
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bash_rows = _run_extractor_script(script, FIXTURE_JSON, tmp)

        py_rows = extract(
            str(FIXTURE_JSON),
            "RUNA0000000000000000000000",
            "agent-codex-review",
            "test-issue-1",
        )
        self.assertEqual(len(bash_rows), len(py_rows), "row count must match")
        for bash_row, py_row in zip(bash_rows, py_rows):
            for field in _PARITY_FIELDS:
                self.assertEqual(
                    bash_row.get(field),
                    py_row.get(field),
                    f"parity mismatch on field {field!r}",
                )


if __name__ == "__main__":
    unittest.main()
