from __future__ import annotations

import json
import unittest
from pathlib import Path

from swarm_do.pipeline.mco_stage import (
    McoStageError,
    build_mco_review_command,
    error_result,
    normalize_mco_review_payload,
    parse_providers,
    read_only_permissions,
    validate_provider_findings_artifact,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class McoStageTests(unittest.TestCase):
    def test_builds_read_only_review_command(self) -> None:
        command = build_mco_review_command(
            mco_bin="mco",
            repo=Path("/repo"),
            prompt="Review this repo.",
            providers=["claude", "codex"],
            timeout_seconds=1800,
            task_id="task-1",
        )

        self.assertEqual(command[:2], ["mco", "review"])
        self.assertIn("--json", command)
        self.assertIn("--strict-contract", command)
        self.assertEqual(command[command.index("--prompt") + 1], "Review this repo.")
        self.assertIn("--provider-permissions-json", command)
        permissions = json.loads(command[command.index("--provider-permissions-json") + 1])
        self.assertEqual(permissions["claude"]["permission_mode"], "plan")
        self.assertEqual(permissions["codex"]["sandbox"], "read-only")
        self.assertEqual(command[-2:], ["--task-id", "task-1"])

    def test_unknown_provider_permissions_fail_closed(self) -> None:
        with self.assertRaises(McoStageError):
            read_only_permissions(["custom-agent"])

    def test_parse_providers_rejects_empty_list(self) -> None:
        with self.assertRaises(McoStageError):
            parse_providers(" , ")

    def test_normalizes_success_fixture_with_consensus_provenance(self) -> None:
        payload = json.loads((FIXTURE_DIR / "mco_review_success.json").read_text(encoding="utf-8"))
        result = normalize_mco_review_payload(
            payload,
            run_id="RUN_MCO",
            issue_id="issue-123",
            stage_id="mco-review-spike",
            selected_providers=["codex", "gemini"],
            source_artifact_path="/tmp/run/mco.stdout.json",
            timestamp="2026-04-24T00:00:00Z",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider_count"], 2)
        self.assertEqual(len(result["findings"]), 1)
        finding = result["findings"][0]
        self.assertEqual(finding["provider"], "mco")
        self.assertEqual(finding["detected_by"], ["codex", "gemini"])
        self.assertEqual(finding["consensus_level"], "confirmed")
        self.assertEqual(finding["consensus_score"], 0.92)
        self.assertEqual(finding["file_path"], "internal/api/foo.go")
        self.assertEqual(finding["line_start"], 42)
        self.assertRegex(finding["stable_finding_hash_v1"], r"^[0-9a-f]{64}$")
        self.assertTrue(finding["schema_ok"])
        validate_provider_findings_artifact(result)

    def test_normalizes_partial_fixture_with_provider_error(self) -> None:
        payload = json.loads((FIXTURE_DIR / "mco_review_partial.json").read_text(encoding="utf-8"))
        result = normalize_mco_review_payload(
            payload,
            run_id="RUN_MCO",
            issue_id="issue-123",
            stage_id="mco-review-spike",
            selected_providers=["codex", "gemini"],
            source_artifact_path="/tmp/run/mco.stdout.json",
            timestamp="2026-04-24T00:00:00Z",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["provider_errors"][0]["provider"], "gemini")
        self.assertEqual(result["provider_errors"][0]["provider_error_class"], "auth")
        self.assertEqual(result["findings"][0]["detected_by"], ["codex"])
        validate_provider_findings_artifact(result)

    def test_normalizes_real_mco_provider_results_shape(self) -> None:
        payload = json.loads((FIXTURE_DIR / "mco_review_provider_results.json").read_text(encoding="utf-8"))
        result = normalize_mco_review_payload(
            payload,
            run_id="RUN_MCO",
            issue_id="issue-123",
            stage_id="mco-review-spike",
            selected_providers=["claude", "codex"],
            source_artifact_path="/tmp/run/mco.stdout.json",
            timestamp="2026-04-24T00:00:00Z",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["provider_count"], 2)
        self.assertEqual(result["provider_errors"][0]["provider"], "codex")
        self.assertEqual(result["provider_errors"][0]["provider_error_class"], "normalization_error")
        finding = result["findings"][0]
        self.assertEqual(finding["detected_by"], ["claude"])
        self.assertEqual(finding["summary"], "Plan uses a second source of truth")
        self.assertEqual(finding["file_path"], "plans/example.md")
        self.assertEqual(finding["line_start"], 42)
        validate_provider_findings_artifact(result)

    def test_normalizes_real_mco_provider_results_with_fenced_json(self) -> None:
        payload = json.loads((FIXTURE_DIR / "mco_review_provider_results.json").read_text(encoding="utf-8"))
        payload["provider_results"]["claude"]["final_text"] = (
            "```json\n" + payload["provider_results"]["claude"]["final_text"] + "\n```"
        )
        result = normalize_mco_review_payload(
            payload,
            run_id="RUN_MCO",
            issue_id="issue-123",
            stage_id="mco-review-spike",
            selected_providers=["claude", "codex"],
            source_artifact_path="/tmp/run/mco.stdout.json",
            timestamp="2026-04-24T00:00:00Z",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["findings"][0]["detected_by"], ["claude"])
        self.assertEqual(result["findings"][0]["file_path"], "plans/example.md")
        validate_provider_findings_artifact(result)

    def test_missing_findings_array_fails_closed(self) -> None:
        with self.assertRaises(McoStageError):
            normalize_mco_review_payload(
                {"providers": []},
                run_id="RUN_MCO",
                issue_id="issue-123",
                stage_id="mco-review-spike",
                selected_providers=["codex"],
                source_artifact_path="/tmp/run/mco.stdout.json",
            )

    def test_error_result_matches_provider_findings_schema(self) -> None:
        result = error_result(
            run_id="RUN_MCO",
            issue_id="issue-123",
            stage_id="mco-review-spike",
            command="review",
            selected_providers=["codex"],
            source_artifact_path="/tmp/run/mco.stdout.json",
            provider_error_class="malformed_output",
            message="not json",
        )

        validate_provider_findings_artifact(result)


if __name__ == "__main__":
    unittest.main()
