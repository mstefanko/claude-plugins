from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from swarm_do.pipeline.provider_review import (
    ReviewProviderResolver,
    build_claude_review_command,
    build_codex_review_command,
    load_emission_schema,
    normalize_provider_review_results,
    run_stage,
    validate_provider_findings_v2_artifact,
)
from swarm_do.pipeline.provider_review import ProviderRunResult
from swarm_do.pipeline.resolver import Route
from swarm_do.telemetry.schemas import validate_value


class ProviderReviewTests(unittest.TestCase):
    def _run_fake_stage(
        self,
        fake_payloads: dict[str, Any],
        *,
        selection: str = "explicit",
        providers: str | None = None,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("Review this repo", encoding="utf-8")
            fake = root / "fake"
            fake.mkdir()
            for provider_id, payload in fake_payloads.items():
                text = payload if isinstance(payload, str) else json.dumps(payload)
                (fake / f"{provider_id}.json").write_text(text, encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = str(root / "data")
            try:
                code = run_stage(
                    argparse.Namespace(
                        repo=str(repo),
                        prompt_file=str(prompt),
                        command="review",
                        selection=selection,
                        providers=providers if providers is not None else ",".join(fake_payloads),
                        max_parallel=4,
                        timeout_seconds=timeout_seconds,
                        output_dir=str(root / "out"),
                        run_id="RUN_PROVIDER",
                        issue_id="issue-1",
                        stage_id="provider-review",
                        fake_result_dir=str(fake),
                    )
                )
                artifact = json.loads((root / "out" / "provider-findings.json").read_text(encoding="utf-8"))
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data
        self.assertEqual(code, 0)
        validate_provider_findings_v2_artifact(artifact)
        return artifact

    def test_emission_schema_accepts_no_findings_and_rejects_swarm_owned_fields(self) -> None:
        schema = load_emission_schema()

        self.assertEqual(validate_value({"findings": []}, schema), [])
        errors = validate_value(
            {
                "run_id": "RUN",
                "findings": [
                    {
                        "severity": "high",
                        "category": "logic",
                        "summary": "Bad branch",
                        "confidence": 0.8,
                    }
                ],
            },
            schema,
        )

        self.assertTrue(any("unexpected property 'run_id'" in error for error in errors))

    def test_command_builders_include_schema_and_read_only_flags(self) -> None:
        route = Route("codex", "gpt-5.4", "high", "test")
        codex = build_codex_review_command(
            codex_bin="codex",
            repo=Path("/repo"),
            prompt="Review",
            schema_file=Path("/schema.json"),
            last_message_file=Path("/last.json"),
            route=route,
        )
        self.assertEqual(codex[:5], ["codex", "exec", "--json", "--sandbox", "read-only"])
        self.assertIn("--output-schema", codex)
        self.assertIn("--output-last-message", codex)
        self.assertEqual(codex[-1], "Review")

        claude = build_claude_review_command(claude_bin="claude", prompt="Review", schema_json='{"type":"object"}')
        self.assertEqual(claude[:4], ["claude", "-p", "--permission-mode", "plan"])
        self.assertIn("--json-schema", claude)
        self.assertEqual(claude[-1], "Review")

    def test_fake_resolver_selects_deterministically(self) -> None:
        resolver = ReviewProviderResolver(fake_providers=("codex", "claude"))
        selection = resolver.select(selection="auto", max_parallel=1)

        self.assertEqual(selection.selected_providers, ("claude",))
        self.assertIn("codex", selection.eligible_providers)
        self.assertEqual(selection.provider_statuses[0].provider_id, "claude")

    def test_normalizes_duplicate_findings_across_schema_valid_providers(self) -> None:
        finding = {
            "severity": "high",
            "category": "logic",
            "summary": "Rejects valid provider output",
            "file_path": "py/swarm_do/pipeline/provider_review.py",
            "line_start": 42,
            "line_end": 42,
            "confidence": 0.9,
            "evidence": "schema_ok is false",
            "recommendation": "Preserve valid outputs",
        }
        artifact = normalize_provider_review_results(
            [
                ProviderRunResult("claude", {"findings": [finding]}, "{}\n", ""),
                ProviderRunResult("codex", {"findings": [finding]}, "{}\n", ""),
            ],
            run_id="RUN_PROVIDER",
            issue_id="issue-1",
            stage_id="provider-review",
            configured_providers=("claude", "codex"),
            selected_providers=("claude", "codex"),
            source_artifact_path="/tmp/provider-findings.json",
            manifest_path="/tmp/provider-review.manifest.json",
            timestamp="2026-04-25T00:00:00Z",
        )

        self.assertEqual(artifact["status"], "ok")
        self.assertEqual(artifact["provider_count"], 2)
        self.assertEqual(len(artifact["findings"]), 1)
        row = artifact["findings"][0]
        self.assertEqual(row["detected_by"], ["claude", "codex"])
        self.assertEqual(row["consensus_level"], "confirmed")
        self.assertAlmostEqual(row["agreement_ratio"], 1.0)
        validate_provider_findings_v2_artifact(artifact)

    def test_secondary_cluster_merges_divergent_summaries_without_confirming(self) -> None:
        first = {
            "severity": "high",
            "category": "logic",
            "summary": "Rejects valid provider output",
            "file_path": "py/swarm_do/pipeline/provider_review.py",
            "line_start": 42,
            "line_end": 42,
            "confidence": 0.9,
        }
        second = {
            **first,
            "summary": "Drops schema-valid provider responses",
            "confidence": 0.8,
        }
        artifact = normalize_provider_review_results(
            [
                ProviderRunResult("claude", {"findings": [first]}, "{}\n", ""),
                ProviderRunResult("codex", {"findings": [second]}, "{}\n", ""),
            ],
            run_id="RUN_PROVIDER",
            issue_id="issue-1",
            stage_id="provider-review",
            configured_providers=("claude", "codex"),
            selected_providers=("claude", "codex"),
            source_artifact_path="/tmp/provider-findings.json",
            manifest_path="/tmp/provider-review.manifest.json",
            timestamp="2026-04-25T00:00:00Z",
        )

        self.assertEqual(len(artifact["findings"]), 1)
        row = artifact["findings"][0]
        self.assertEqual(row["detected_by"], ["claude", "codex"])
        self.assertEqual(row["consensus_level"], "needs-verification")
        self.assertIsNotNone(row["duplicate_cluster_id"])
        validate_provider_findings_v2_artifact(artifact)

    def test_malformed_provider_output_is_partial_when_another_provider_is_valid(self) -> None:
        artifact = normalize_provider_review_results(
            [
                ProviderRunResult("claude", {"findings": []}, "{}\n", ""),
                ProviderRunResult("codex", {"run_id": "model-owned"}, "{}\n", ""),
            ],
            run_id="RUN_PROVIDER",
            issue_id="issue-1",
            stage_id="provider-review",
            configured_providers=("claude", "codex"),
            selected_providers=("claude", "codex"),
            source_artifact_path="/tmp/provider-findings.json",
            manifest_path="/tmp/provider-review.manifest.json",
            timestamp="2026-04-25T00:00:00Z",
        )

        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "codex")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "malformed_output")
        validate_provider_findings_v2_artifact(artifact)

    def test_run_stage_writes_fake_sidecars_and_v2_artifact(self) -> None:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("Review this repo", encoding="utf-8")
            fake = root / "fake"
            fake.mkdir()
            (fake / "claude.json").write_text(json.dumps({"findings": []}), encoding="utf-8")
            (fake / "codex.json").write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "severity": "medium",
                                "category": "test",
                                "summary": "Missing assertion",
                                "file_path": "tests/test_provider_review.py",
                                "line_start": 10,
                                "line_end": 10,
                                "confidence": 0.7,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = str(root / "data")
            try:
                code = run_stage(
                    argparse.Namespace(
                        repo=str(repo),
                        prompt_file=str(prompt),
                        command="review",
                        selection="explicit",
                        providers="claude,codex",
                        max_parallel=2,
                        timeout_seconds=30,
                        output_dir=str(root / "out"),
                        run_id="RUN_PROVIDER",
                        issue_id="issue-1",
                        stage_id="provider-review",
                        fake_result_dir=str(fake),
                    )
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

            self.assertEqual(code, 0)
            artifact = json.loads((root / "out" / "provider-findings.json").read_text(encoding="utf-8"))
            self.assertEqual(artifact["status"], "ok")
            self.assertEqual(artifact["provider_count"], 2)
            self.assertTrue((root / "out" / "providers" / "claude" / "last-message.json").is_file())
            validate_provider_findings_v2_artifact(artifact)

    def test_run_stage_writes_skipped_artifact_when_selection_is_off(self) -> None:
        artifact = self._run_fake_stage(
            {"claude": {"findings": []}, "codex": {"findings": []}},
            selection="off",
            providers="claude,codex",
        )

        self.assertEqual(artifact["status"], "skipped")
        self.assertEqual(artifact["selected_providers"], [])
        self.assertEqual(artifact["launched_providers"], [])
        self.assertEqual(artifact["provider_count"], 0)

    def test_run_stage_writes_skipped_artifact_when_no_provider_is_eligible(self) -> None:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        old_path = os.environ.get("PATH")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("Review this repo", encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = str(root / "data")
            os.environ["PATH"] = ""
            try:
                code = run_stage(
                    argparse.Namespace(
                        repo=str(repo),
                        prompt_file=str(prompt),
                        command="review",
                        selection="auto",
                        providers=None,
                        max_parallel=4,
                        timeout_seconds=30,
                        output_dir=str(root / "out"),
                        run_id="RUN_PROVIDER",
                        issue_id="issue-1",
                        stage_id="provider-review",
                        fake_result_dir=None,
                    )
                )
                artifact = json.loads((root / "out" / "provider-findings.json").read_text(encoding="utf-8"))
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data
                if old_path is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = old_path

        self.assertEqual(code, 0)
        self.assertEqual(artifact["status"], "skipped")
        self.assertEqual(artifact["selected_providers"], [])
        self.assertEqual(artifact["launched_providers"], [])
        validate_provider_findings_v2_artifact(artifact)

    def test_run_stage_records_partial_fake_provider_failure(self) -> None:
        artifact = self._run_fake_stage(
            {
                "claude": {"findings": []},
                "codex": {"_fake_error": {"class": "auth", "message": "not authenticated"}, "findings": []},
            }
        )

        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "codex")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "auth")

    def test_run_stage_records_partial_malformed_fake_output(self) -> None:
        artifact = self._run_fake_stage(
            {
                "claude": {"findings": []},
                "codex": "{not-json",
            }
        )

        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "codex")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "malformed_output")

    def test_run_stage_records_partial_fake_timeout(self) -> None:
        artifact = self._run_fake_stage(
            {
                "claude": {"findings": []},
                "codex": {"_fake_sleep_seconds": 31, "findings": []},
            },
            timeout_seconds=30,
        )

        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "codex")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "timeout")

    def test_run_stage_accepts_all_no_finding_fake_outputs(self) -> None:
        artifact = self._run_fake_stage(
            {
                "claude": {"findings": []},
                "codex": {"findings": []},
            }
        )

        self.assertEqual(artifact["status"], "ok")
        self.assertEqual(artifact["provider_count"], 2)
        self.assertEqual(artifact["findings"], [])


if __name__ == "__main__":
    unittest.main()
