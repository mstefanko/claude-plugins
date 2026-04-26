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
        self.assertEqual(
            codex,
            [
                "codex",
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "-C",
                "/repo",
                "--output-schema",
                "/schema.json",
                "--output-last-message",
                "/last.json",
                "-m",
                "gpt-5.4",
                "-c",
                'model_reasoning_effort="high"',
                "Review",
            ],
        )

        claude = build_claude_review_command(claude_bin="claude", prompt="Review", schema_json='{"type":"object"}')
        self.assertEqual(
            claude,
            [
                "claude",
                "-p",
                "--permission-mode",
                "plan",
                "--output-format",
                "json",
                "--json-schema",
                '{"type":"object"}',
                "Review",
            ],
        )

    def test_real_resolver_reports_exact_detected_cli_flags_but_stays_ineligible(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "codex"} else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                stdout = "Usage: claude -p --permission-mode --output-format --json-schema"
            elif args == ["codex", "exec", "--help"]:
                stdout = "Usage: codex exec --json --sandbox --output-schema --output-last-message"
            elif args == ["claude", "--version"]:
                stdout = "claude 1.0"
            elif args == ["codex", "--version"]:
                stdout = "codex 1.0"
            else:
                stdout = ""
            return argparse.Namespace(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                statuses = ReviewProviderResolver(which=which, runner=runner).statuses()
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        by_id = {status.provider_id: status for status in statuses}
        self.assertEqual(by_id["claude"].schema_flags, ("-p", "--json-schema", "--output-format"))
        self.assertEqual(by_id["claude"].read_only_flags, ("--permission-mode",))
        self.assertEqual(by_id["codex"].schema_flags, ("--json", "--output-schema", "--output-last-message"))
        self.assertEqual(by_id["codex"].read_only_flags, ("--sandbox",))
        self.assertEqual(by_id["codex"].schema_mode, "native")
        self.assertEqual(by_id["codex"].read_only_mode, "flag-detected")
        self.assertFalse(by_id["codex"].eligible)
        self.assertIn("Phase 0 write-denial proof not complete", by_id["codex"].reason)

    def test_real_resolver_fails_command_surface_closed_when_required_flag_is_missing(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd == "codex" else None

        def runner(args, **kwargs):
            if args == ["codex", "exec", "--help"]:
                stdout = "Usage: codex exec --sandbox --output-schema --output-last-message"
            elif args == ["codex", "--version"]:
                stdout = "codex 1.0"
            else:
                stdout = ""
            return argparse.Namespace(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                codex = next(
                    status
                    for status in ReviewProviderResolver(which=which, runner=runner).statuses()
                    if status.provider_id == "codex"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(codex.schema_mode, "unavailable")
        self.assertEqual(codex.missing_schema_flags, ("--json",))
        self.assertIsNotNone(codex.probe)
        self.assertFalse(codex.probe.schema.ready)
        self.assertEqual(codex.probe.schema.status, "error")
        self.assertEqual(codex.probe.schema.data["missing_flags"], ["--json"])
        self.assertIn("structured-output flags not detected: --json", codex.reason)
        self.assertFalse(codex.eligible)

    def test_real_resolver_probe_reports_installed_but_route_mismatch(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd == "codex" else None

        def runner(args, **kwargs):
            if args == ["codex", "exec", "--help"]:
                stdout = "Usage: codex exec --json --sandbox --output-schema --output-last-message"
            elif args == ["codex", "--version"]:
                stdout = "codex 1.0"
            else:
                stdout = ""
            return argparse.Namespace(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "backends.toml").write_text(
                """
[roles.agent-codex-review]
backend = "claude"
model = "claude-opus-4-7"
effort = "high"
""".lstrip(),
                encoding="utf-8",
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                codex = next(
                    status
                    for status in ReviewProviderResolver(which=which, runner=runner).statuses()
                    if status.provider_id == "codex"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(codex.status, "skipped")
        self.assertEqual(codex.executable, "/bin/codex")
        self.assertIsNotNone(codex.probe)
        self.assertFalse(codex.probe.configured.ready)
        self.assertTrue(codex.probe.installed.ready)
        self.assertIn("role route resolves to backend claude, not codex", codex.probe.configured.reason)
        self.assertIn("configured", codex.probe.blockers)
        self.assertFalse(codex.eligible)

    def test_real_resolver_probe_reports_disabled_by_policy(self) -> None:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "backends.toml").write_text(
                """
[review_providers.codex]
enabled = false
""".lstrip(),
                encoding="utf-8",
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                codex = next(
                    status
                    for status in ReviewProviderResolver(which=lambda cmd: f"/bin/{cmd}").statuses()
                    if status.provider_id == "codex"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(codex.status, "skipped")
        self.assertIsNotNone(codex.probe)
        self.assertEqual(codex.probe.configured.status, "skipped")
        self.assertFalse(codex.probe.configured.ready)
        self.assertIn("disabled by review_providers config", codex.reason)

    def test_reserved_gemini_probe_reports_unsupported_schema_mode(self) -> None:
        gemini = next(
            status
            for status in ReviewProviderResolver(which=lambda cmd: "/bin/gemini" if cmd == "gemini" else None).statuses()
            if status.provider_id == "gemini"
        )

        self.assertEqual(gemini.status, "skipped")
        self.assertEqual(gemini.schema_mode, "unavailable")
        self.assertIsNotNone(gemini.probe)
        self.assertTrue(gemini.probe.installed.ready)
        self.assertEqual(gemini.probe.schema.status, "error")
        self.assertIn("native schema mode unavailable", gemini.probe.schema.reason)

    def test_real_resolver_does_not_count_cli_flag_substrings_as_detected(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd == "claude" else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                stdout = "Usage: claude --permission-mode --output-format --json-schema"
            elif args == ["claude", "--version"]:
                stdout = "claude 1.0"
            else:
                stdout = ""
            return argparse.Namespace(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                claude = next(
                    status
                    for status in ReviewProviderResolver(which=which, runner=runner).statuses()
                    if status.provider_id == "claude"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(claude.schema_flags, ("--json-schema", "--output-format"))
        self.assertEqual(claude.missing_schema_flags, ("-p",))
        self.assertEqual(claude.schema_mode, "unavailable")

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
