from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.mco_stage import normalize_mco_review_payload
from swarm_do.pipeline.provider_evidence import provider_evidence_summary, provider_evidence_summary_from_file
from swarm_do.pipeline.provider_review import ProviderRunResult, normalize_provider_review_results


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class ProviderEvidenceTests(unittest.TestCase):
    def test_summarizes_swarm_review_without_raw_evidence_text(self) -> None:
        artifact = normalize_provider_review_results(
            [
                ProviderRunResult(
                    "claude",
                    {
                        "findings": [
                            {
                                "severity": "high",
                                "category": "logic",
                                "summary": "Rejects valid provider output",
                                "file_path": "py/swarm_do/pipeline/provider_review.py",
                                "line_start": 42,
                                "line_end": 42,
                                "confidence": 0.9,
                                "evidence": "raw provider evidence snippet should not be echoed",
                                "recommendation": "Preserve valid outputs",
                            }
                        ]
                    },
                    "{}\n",
                    "",
                ),
                ProviderRunResult("codex", None, "", "timeout", "timeout", "provider timed out after 30s"),
            ],
            run_id="RUN_PROVIDER",
            issue_id="issue-1",
            stage_id="provider-review",
            configured_providers=("claude", "codex"),
            selected_providers=("claude", "codex"),
            source_artifact_path="/tmp/provider-findings.json",
            manifest_path="/tmp/provider-review.manifest.json",
            min_success=2,
            selection_result="selected",
            timestamp="2026-04-25T00:00:00Z",
        )

        summary = provider_evidence_summary(artifact, artifact_path="/tmp/provider-findings.json")

        self.assertIn("Provider Review Evidence", summary)
        self.assertIn("status: swarm-review partial", summary)
        self.assertIn("provider_count=1", summary)
        self.assertIn("min_success=2", summary)
        self.assertIn("single_provider_findings=needs-verification", summary)
        self.assertIn("high/logic swarm-do/py/swarm_do/pipeline/provider_review.py:42", summary)
        self.assertIn("codex timeout", summary)
        self.assertNotIn("raw provider evidence snippet", summary)
        self.assertNotIn("Preserve valid outputs", summary)

    def test_summarizes_mco_v1_artifact_from_file(self) -> None:
        payload = json.loads((FIXTURE_DIR / "mco_review_success.json").read_text(encoding="utf-8"))
        artifact = normalize_mco_review_payload(
            payload,
            run_id="RUN_MCO",
            issue_id="issue-123",
            stage_id="mco-review-spike",
            selected_providers=["codex", "gemini"],
            source_artifact_path="/tmp/run/mco.stdout.json",
            timestamp="2026-04-24T00:00:00Z",
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "provider-findings.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            summary = provider_evidence_summary_from_file(path)

        self.assertIn("status: mco ok", summary)
        self.assertIn("selected=codex,gemini", summary)
        self.assertIn("provider_count=2", summary)
        self.assertIn("confirmed", summary)


if __name__ == "__main__":
    unittest.main()
