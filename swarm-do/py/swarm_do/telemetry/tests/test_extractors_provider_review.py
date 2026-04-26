from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.telemetry.extractors import main
from swarm_do.telemetry.extractors.provider_review import extract
from swarm_do.telemetry.schemas import load_schema, validate_value


def _artifact() -> dict:
    return {
        "schema_version": "provider-findings.v2-draft",
        "findings": [
            {
                "finding_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "run_id": "RUN_FROM_ARTIFACT",
                "timestamp": "2026-04-25T00:00:00Z",
                "role": "agent-review",
                "issue_id": "issue-from-artifact",
                "provider": "swarm-review",
                "provider_count": 1,
                "detected_by": ["codex"],
                "agreement_ratio": 1.0,
                "max_confidence": 0.9,
                "consensus_score": 0.9,
                "consensus_level": "needs-verification",
                "source_artifact_path": "/tmp/provider-findings.json",
                "provider_error_class": None,
                "severity": "high",
                "category": "logic",
                "summary": "Rejects valid provider output",
                "short_summary": "valid provider output",
                "file_path": "pkg/review.py",
                "line_start": 42,
                "line_end": 42,
                "stable_finding_hash_v1": "a" * 64,
                "duplicate_cluster_id": None,
                "schema_ok": True,
                "evidence": "bounded evidence stays in artifact only",
                "recommendation": "Fix the branch",
            }
        ],
    }


class ProviderReviewExtractorTests(unittest.TestCase):
    def test_extract_down_converts_v2_artifact_to_findings_ledger_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "provider-findings.json"
            path.write_text(json.dumps(_artifact()), encoding="utf-8")

            rows = extract(str(path), "RUN_PROVIDER", "swarm-review", "issue-1")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["run_id"], "RUN_PROVIDER")
        self.assertEqual(row["role"], "agent-review")
        self.assertEqual(row["issue_id"], "issue-1")
        self.assertNotIn("provider", row)
        self.assertEqual(validate_value(row, load_schema("findings")), [])

    def test_dispatcher_appends_provider_review_rows_to_findings_jsonl(self) -> None:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact_path = root / "provider-findings.json"
            artifact_path.write_text(json.dumps(_artifact()), encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = str(root / "data")
            try:
                code = main([str(artifact_path), "RUN_PROVIDER", "swarm-review", "issue-1"])
                out_path = root / "data" / "telemetry" / "findings.jsonl"
                rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "agent-review")
        self.assertEqual(validate_value(rows[0], load_schema("findings")), [])


if __name__ == "__main__":
    unittest.main()
