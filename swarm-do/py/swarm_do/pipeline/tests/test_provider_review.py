from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from swarm_do.pipeline.cli import cmd_providers_calibrate_consensus
from swarm_do.pipeline.provider_review import (
    CLAUDE_WRITE_DENIAL_CREATE_PATH,
    CLAUDE_WRITE_DENIAL_DELETE_PATH,
    CLAUDE_WRITE_DENIAL_EDIT_PATH,
    DEFAULT_CLAUDE_R3_TIMEOUT_SECONDS,
    DEFAULT_CODEX_R2_TIMEOUT_SECONDS,
    ReviewProviderResolver,
    ReviewProviderProbeCheck,
    calibrate_consensus_samples,
    build_claude_review_command,
    build_codex_review_command,
    format_consensus_calibration_report,
    load_emission_schema,
    normalize_provider_review_results,
    run_claude_auth_status_probe,
    run_claude_write_denial_fixture,
    run_codex_auth_status_probe,
    run_codex_structured_output_smoke_fixture,
    run_codex_write_denial_fixture,
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
        min_success: int | None = None,
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
                        min_success=min_success,
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

    def _run_realish_stage(
        self,
        providers: tuple[str, ...],
        *,
        runner,
        resolver_factory,
        timeout_seconds: int = 30,
    ) -> tuple[int, dict[str, Any], dict[str, dict[str, Any]]]:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("Review this repo", encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = str(root / "data")
            try:
                resolver = resolver_factory()
                code = run_stage(
                    argparse.Namespace(
                        repo=str(repo),
                        prompt_file=str(prompt),
                        command="review",
                        selection="explicit",
                        providers=",".join(providers),
                        max_parallel=4,
                        min_success=None,
                        timeout_seconds=timeout_seconds,
                        output_dir=str(root / "out"),
                        run_id="RUN_PROVIDER",
                        issue_id="issue-1",
                        stage_id="provider-review",
                        fake_result_dir=None,
                        runner=runner,
                        resolver=resolver,
                    )
                )
                artifact = json.loads((root / "out" / "provider-findings.json").read_text(encoding="utf-8"))
                sidecars: dict[str, dict[str, Any]] = {}
                for provider_id in providers:
                    provider_dir = root / "out" / "providers" / provider_id.replace(":", "_")
                    if not provider_dir.is_dir():
                        continue
                    sidecars[provider_id] = {
                        "stdout": (provider_dir / "stdout.jsonl").read_text(encoding="utf-8"),
                        "stderr": (provider_dir / "stderr.txt").read_text(encoding="utf-8"),
                        "last_message": (provider_dir / "last-message.json").read_text(encoding="utf-8"),
                        "meta": json.loads((provider_dir / "meta.json").read_text(encoding="utf-8")),
                    }
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data
        validate_provider_findings_v2_artifact(artifact)
        return code, artifact, sidecars

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

    def test_claude_write_denial_fixture_uses_exact_plan_command_and_passes_fail_closed(self) -> None:
        captured: list[tuple[list[str], Path | None]] = []

        def runner(args, **kwargs):
            captured.append((list(args), kwargs.get("cwd")))
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="plan mode denied")

        with tempfile.TemporaryDirectory() as td:
            result = run_claude_write_denial_fixture(
                claude_bin="/bin/claude",
                runner=runner,
                timeout_seconds=5,
                work_root=Path(td),
            )

        self.assertTrue(result.ready, result.reason)
        self.assertEqual(result.status, "ok")
        command = captured[0][0]
        self.assertEqual(command[:5], ["/bin/claude", "-p", "--permission-mode", "plan", "--output-format"])
        self.assertIn("--json-schema", command)
        self.assertIsNotNone(captured[0][1])
        self.assertEqual(result.data["mutation_checks"], {"create_denied": True, "edit_denied": True, "delete_denied": True})

    def test_claude_write_denial_fixture_fails_when_plan_mode_allows_mutation(self) -> None:
        def runner(args, **kwargs):
            repo = Path(kwargs["cwd"])
            (repo / CLAUDE_WRITE_DENIAL_CREATE_PATH).write_text("created", encoding="utf-8")
            (repo / CLAUDE_WRITE_DENIAL_EDIT_PATH).write_text("edited", encoding="utf-8")
            (repo / CLAUDE_WRITE_DENIAL_DELETE_PATH).unlink()
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"findings": []}), stderr="")

        with tempfile.TemporaryDirectory() as td:
            result = run_claude_write_denial_fixture(
                claude_bin="/bin/claude",
                runner=runner,
                timeout_seconds=5,
                work_root=Path(td),
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "error")
        self.assertIn("allowed repo mutations", result.reason)
        self.assertEqual(result.data["mutation_checks"], {"create_denied": False, "edit_denied": False, "delete_denied": False})

    def test_claude_write_denial_fixture_validates_schema_when_command_succeeds(self) -> None:
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"result": json.dumps({"findings": []})}),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as td:
            result = run_claude_write_denial_fixture(
                claude_bin="/bin/claude",
                runner=runner,
                timeout_seconds=5,
                work_root=Path(td),
            )

        self.assertTrue(result.ready, result.reason)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["schema_mode"], "native")
        self.assertEqual(result.data["finding_count"], 0)

    def test_codex_write_denial_fixture_uses_exact_read_only_command_and_passes_fail_closed(self) -> None:
        captured: list[list[str]] = []

        def runner(args, **kwargs):
            captured.append(list(args))
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="sandbox denied")

        with tempfile.TemporaryDirectory() as td:
            result = run_codex_write_denial_fixture(
                codex_bin="/bin/codex",
                runner=runner,
                timeout_seconds=5,
                work_root=Path(td),
            )

        self.assertTrue(result.ready, result.reason)
        self.assertEqual(result.status, "ok")
        self.assertEqual(captured[0][:5], ["/bin/codex", "exec", "--json", "--sandbox", "read-only"])
        self.assertIn("-C", captured[0])
        self.assertIn("--output-schema", captured[0])
        self.assertIn("--output-last-message", captured[0])
        self.assertEqual(result.data["mutation_checks"], {"create_denied": True, "edit_denied": True, "delete_denied": True})

    def test_codex_write_denial_fixture_fails_when_sandbox_allows_mutation(self) -> None:
        def runner(args, **kwargs):
            repo = Path(args[args.index("-C") + 1])
            (repo / "codex-created.txt").write_text("created", encoding="utf-8")
            (repo / "codex-edit-target.txt").write_text("edited", encoding="utf-8")
            (repo / "codex-delete-target.txt").unlink()
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as td:
            result = run_codex_write_denial_fixture(
                codex_bin="/bin/codex",
                runner=runner,
                timeout_seconds=5,
                work_root=Path(td),
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "error")
        self.assertIn("allowed repo mutations", result.reason)
        self.assertEqual(result.data["mutation_checks"], {"create_denied": False, "edit_denied": False, "delete_denied": False})

    def test_codex_structured_output_smoke_fixture_validates_last_message_schema(self) -> None:
        captured: list[list[str]] = []

        def runner(args, **kwargs):
            captured.append(list(args))
            last_message = Path(args[args.index("--output-last-message") + 1])
            last_message.write_text(json.dumps({"findings": []}), encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"event":"done"}\n', stderr="")

        with tempfile.TemporaryDirectory() as td:
            result = run_codex_structured_output_smoke_fixture(
                codex_bin="/bin/codex",
                runner=runner,
                timeout_seconds=5,
                work_root=Path(td),
            )

        self.assertTrue(result.ready, result.reason)
        self.assertEqual(result.status, "ok")
        self.assertEqual(captured[0][:5], ["/bin/codex", "exec", "--json", "--sandbox", "read-only"])
        self.assertEqual(result.data["schema_mode"], "native")
        self.assertEqual(result.data["finding_count"], 0)

    @unittest.skipUnless(
        os.environ.get("SWARM_RUN_CODEX_R2_FIXTURE") == "1",
        "set SWARM_RUN_CODEX_R2_FIXTURE=1 to launch the real bounded Codex R2 fixtures",
    )
    def test_local_codex_r2_fixtures_pass_when_explicitly_enabled(self) -> None:
        timeout = int(os.environ.get("SWARM_CODEX_R2_TIMEOUT_SECONDS", str(DEFAULT_CODEX_R2_TIMEOUT_SECONDS)))
        codex_bin = os.environ.get("SWARM_CODEX_BIN", "codex")

        schema_result = run_codex_structured_output_smoke_fixture(codex_bin=codex_bin, timeout_seconds=timeout)
        read_only_result = run_codex_write_denial_fixture(codex_bin=codex_bin, timeout_seconds=timeout)

        self.assertTrue(schema_result.ready, schema_result.as_probe_check().as_dict())
        self.assertTrue(read_only_result.ready, read_only_result.as_probe_check().as_dict())

    @unittest.skipUnless(
        os.environ.get("SWARM_RUN_CLAUDE_R3_FIXTURE") == "1",
        "set SWARM_RUN_CLAUDE_R3_FIXTURE=1 to launch the real bounded Claude R3 fixture",
    )
    def test_local_claude_r3_fixture_passes_when_explicitly_enabled(self) -> None:
        timeout = int(os.environ.get("SWARM_CLAUDE_R3_TIMEOUT_SECONDS", str(DEFAULT_CLAUDE_R3_TIMEOUT_SECONDS)))
        claude_bin = os.environ.get("SWARM_CLAUDE_BIN", "claude")

        read_only_result = run_claude_write_denial_fixture(claude_bin=claude_bin, timeout_seconds=timeout)

        self.assertTrue(read_only_result.ready, read_only_result.as_probe_check().as_dict())

    def test_r4_auth_status_probes_distinguish_authenticated_and_not_authenticated(self) -> None:
        def runner(args, **kwargs):
            if args == ["claude", "auth", "status", "--json"]:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=1,
                    stdout=json.dumps({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}),
                    stderr="",
                )
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="Logged in using ChatGPT\n", stderr="")
            raise AssertionError(args)

        claude = run_claude_auth_status_probe(runner=runner)
        codex = run_codex_auth_status_probe(runner=runner)
        codex_not_ready = run_codex_auth_status_probe(
            runner=lambda args, **kwargs: subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="Not currently logged in\n",
                stderr="",
            )
        )

        self.assertFalse(claude.ready)
        self.assertEqual(claude.status, "warning")
        self.assertEqual(claude.data["failure_class"], "not_authenticated")
        self.assertTrue(codex.ready)
        self.assertEqual(codex.status, "ok")
        self.assertFalse(codex_not_ready.ready)
        self.assertEqual(codex_not_ready.data["failure_class"], "not_authenticated")

    def test_r4_auth_status_probe_reports_spend_probe_required_when_status_command_is_absent(self) -> None:
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=2, stdout="", stderr="unknown command: status")

        claude = run_claude_auth_status_probe(runner=runner)
        codex = run_codex_auth_status_probe(runner=runner)

        self.assertFalse(claude.ready)
        self.assertEqual(claude.data["failure_class"], "spend_probe_required")
        self.assertIn("bounded spend probe required", claude.reason)
        self.assertFalse(codex.ready)
        self.assertEqual(codex.data["failure_class"], "spend_probe_required")

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
            elif args == ["claude", "auth", "status", "--json"]:
                stdout = json.dumps({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"})
                return argparse.Namespace(args=args, returncode=1, stdout=stdout, stderr="")
            elif args == ["codex", "login", "status"]:
                stdout = "Logged in using ChatGPT\n"
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
        self.assertIsNotNone(by_id["codex"].probe)
        self.assertEqual(by_id["codex"].probe.schema.status, "warning")
        self.assertEqual(by_id["codex"].probe.read_only.status, "warning")
        self.assertIn("schema", by_id["codex"].probe.blockers)
        self.assertIn("read_only", by_id["codex"].probe.blockers)
        self.assertNotIn("auth", by_id["codex"].probe.blockers)
        self.assertIn("Phase R2 schema smoke proof not complete", by_id["codex"].reason)
        self.assertIn("Phase R2 write-denial proof not complete", by_id["codex"].reason)
        self.assertEqual(by_id["claude"].probe.auth.data["failure_class"], "not_authenticated")

    def test_codex_r2_proofs_clear_schema_and_read_only_gates_but_not_auth(self) -> None:
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
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                codex = next(
                    status
                    for status in ReviewProviderResolver(
                        which=which,
                        runner=runner,
                        codex_schema_probe=ReviewProviderProbeCheck(
                            "ok",
                            True,
                            "Codex structured-output smoke produced schema-valid provider emission",
                        ),
                        codex_read_only_probe=ReviewProviderProbeCheck(
                            "ok",
                            True,
                            "Codex write-denial fixture completed without repo mutations",
                        ),
                    ).statuses()
                    if status.provider_id == "codex"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(codex.schema_mode, "native")
        self.assertEqual(codex.read_only_mode, "confirmed")
        self.assertIsNotNone(codex.probe)
        self.assertTrue(codex.probe.schema.ready)
        self.assertTrue(codex.probe.read_only.ready)
        self.assertEqual(codex.probe.blockers, ("auth",))
        self.assertFalse(codex.eligible)
        self.assertIn("Codex login status did not prove authentication readiness", codex.reason)

    def test_codex_becomes_eligible_when_r2_and_r4_proofs_are_ready(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd == "codex" else None

        def runner(args, **kwargs):
            if args == ["codex", "exec", "--help"]:
                stdout = "Usage: codex exec --json --sandbox --output-schema --output-last-message"
            elif args == ["codex", "--version"]:
                stdout = "codex 1.0"
            elif args == ["codex", "login", "status"]:
                stdout = "Logged in using ChatGPT\n"
            else:
                stdout = ""
            return argparse.Namespace(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                codex = next(
                    status
                    for status in ReviewProviderResolver(
                        which=which,
                        runner=runner,
                        codex_schema_probe=ReviewProviderProbeCheck(
                            "ok",
                            True,
                            "Codex structured-output smoke produced schema-valid provider emission",
                        ),
                        codex_read_only_probe=ReviewProviderProbeCheck(
                            "ok",
                            True,
                            "Codex write-denial fixture completed without repo mutations",
                        ),
                    ).statuses()
                    if status.provider_id == "codex"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertTrue(codex.eligible, codex.reason)
        self.assertIsNotNone(codex.probe)
        self.assertTrue(codex.probe.auth.ready)
        self.assertEqual(codex.probe.blockers, ())

    def test_claude_r3_proof_clears_read_only_gate_but_auth_still_blocks(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd == "claude" else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                stdout = "Usage: claude -p --permission-mode --output-format --json-schema"
            elif args == ["claude", "--version"]:
                stdout = "claude 1.0"
            elif args == ["claude", "auth", "status", "--json"]:
                stdout = json.dumps({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"})
                return argparse.Namespace(args=args, returncode=1, stdout=stdout, stderr="")
            else:
                stdout = ""
            return argparse.Namespace(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                claude = next(
                    status
                    for status in ReviewProviderResolver(
                        which=which,
                        runner=runner,
                        claude_read_only_probe=ReviewProviderProbeCheck(
                            "ok",
                            True,
                            "Claude write-denial fixture completed without repo mutations",
                        ),
                    ).statuses()
                    if status.provider_id == "claude"
                )
            finally:
                if old_data is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old_data

        self.assertEqual(claude.schema_mode, "native")
        self.assertEqual(claude.read_only_mode, "confirmed")
        self.assertIsNotNone(claude.probe)
        self.assertTrue(claude.probe.schema.ready)
        self.assertTrue(claude.probe.read_only.ready)
        self.assertEqual(claude.probe.blockers, ("auth",))
        self.assertFalse(claude.eligible)
        self.assertIn("not authenticated", claude.reason)

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

    def test_consensus_calibration_measures_cluster_errors_and_keeps_policy_conservative(self) -> None:
        same_anchor_first = {
            "severity": "high",
            "category": "logic",
            "summary": "Rejects valid provider output",
            "file_path": "py/swarm_do/pipeline/provider_review.py",
            "line_start": 42,
            "line_end": 42,
            "confidence": 0.9,
        }
        same_anchor_second = {
            **same_anchor_first,
            "summary": "Drops schema-valid provider responses",
        }
        split_anchor_first = {
            "severity": "medium",
            "category": "test",
            "summary": "Missing first assertion",
            "file_path": "tests/test_provider_review.py",
            "line_start": 10,
            "line_end": 10,
            "confidence": 0.8,
        }
        split_anchor_second = {
            **split_anchor_first,
            "summary": "Missing second assertion",
            "line_start": 20,
            "line_end": 20,
        }
        report = calibrate_consensus_samples(
            {
                "schema_version": "provider-review.consensus-calibration.samples.v1",
                "samples": [
                    {
                        "sample_id": "false-merge",
                        "provider_outputs": [
                            {
                                "provider_id": "claude",
                                "findings": [
                                    {"expected_cluster_id": "logic-a", "emission": same_anchor_first},
                                ],
                            },
                            {
                                "provider_id": "codex",
                                "findings": [
                                    {"expected_cluster_id": "logic-b", "emission": same_anchor_second},
                                ],
                            },
                        ],
                    },
                    {
                        "sample_id": "false-split",
                        "provider_outputs": [
                            {
                                "provider_id": "claude",
                                "findings": [
                                    {"expected_cluster_id": "test-a", "emission": split_anchor_first},
                                ],
                            },
                            {
                                "provider_id": "codex",
                                "findings": [
                                    {"expected_cluster_id": "test-a", "emission": split_anchor_second},
                                ],
                            },
                        ],
                    },
                ],
            },
            timestamp="2026-04-25T00:00:00Z",
        )

        self.assertEqual(report["schema_version"], "provider-review.consensus-calibration.v1")
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["false_merge_count"], 1)
        self.assertEqual(report["false_split_count"], 1)
        self.assertEqual(report["consensus_policy"]["secondary_cluster_promotion"], "disabled")
        self.assertEqual(report["consensus_policy"]["single_provider_findings"], "needs-verification")
        self.assertEqual(report["consensus_policy"]["stock_auto_min_success"], 1)
        rendered = format_consensus_calibration_report(report)
        self.assertIn("secondary_cluster_promotion: disabled", rendered)
        self.assertIn("stock_auto_min_success: 1", rendered)

    def test_consensus_calibration_cli_writes_report_and_renders_summary(self) -> None:
        sample = {
            "schema_version": "provider-review.consensus-calibration.samples.v1",
            "samples": [
                {
                    "sample_id": "empty",
                    "provider_outputs": [
                        {"provider_id": "claude", "findings": []},
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            samples_path = root / "samples.json"
            report_path = root / "report.json"
            samples_path.write_text(json.dumps(sample), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cmd_providers_calibrate_consensus(
                    argparse.Namespace(samples=str(samples_path), output=str(report_path), json=False)
                )

            self.assertEqual(code, 0)
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], "provider-review.consensus-calibration.v1")
            self.assertIn("Provider review consensus calibration", stdout.getvalue())
            self.assertIn(str(report_path), stdout.getvalue())

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

    def test_min_success_is_enforced_against_schema_valid_provider_outputs(self) -> None:
        artifact = self._run_fake_stage(
            {"claude": {"findings": []}},
            providers="claude",
            min_success=2,
        )

        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["schema_valid_providers"], ["claude"])
        self.assertEqual(artifact["min_success"], 2)
        self.assertIn("selected provider count 1 below min_success 2", artifact["status_reason"])
        self.assertIn("schema-valid provider count 1 below min_success 2", artifact["status_reason"])

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

    def test_run_stage_runs_real_codex_when_r2_and_r4_gates_are_ready(self) -> None:
        def which(cmd: str) -> str | None:
            return "/bin/codex" if cmd == "codex" else None

        def runner(args, **kwargs):
            if args == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="--json --sandbox --output-schema --output-last-message", stderr="")
            if args == ["codex", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="codex 1.0", stderr="")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="Logged in using ChatGPT\n", stderr="")
            if args[:2] == ["/bin/codex", "exec"]:
                last_message = Path(args[args.index("--output-last-message") + 1])
                last_message.parent.mkdir(parents=True, exist_ok=True)
                last_message.write_text(json.dumps({"findings": []}), encoding="utf-8")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"event":"done"}\n', stderr="")
            raise AssertionError(args)

        def resolver_factory():
            return ReviewProviderResolver(
                which=which,
                runner=runner,
                codex_schema_probe=ReviewProviderProbeCheck("ok", True, "Codex schema proof green"),
                codex_read_only_probe=ReviewProviderProbeCheck("ok", True, "Codex read-only proof green"),
            )

        code, artifact, sidecars = self._run_realish_stage(("codex",), runner=runner, resolver_factory=resolver_factory)

        self.assertEqual(code, 0)
        self.assertEqual(artifact["status"], "ok")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["selected_providers"], ["codex"])
        self.assertEqual(artifact["launched_providers"], ["codex"])
        self.assertEqual(sidecars["codex"]["meta"]["command_argv"][:5], ["/bin/codex", "exec", "--json", "--sandbox", "read-only"])
        self.assertEqual(json.loads(sidecars["codex"]["last_message"]), {"findings": []})

    def test_run_stage_records_malformed_real_codex_output_without_crashing(self) -> None:
        def which(cmd: str) -> str | None:
            return "/bin/codex" if cmd == "codex" else None

        def runner(args, **kwargs):
            if args == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="--json --sandbox --output-schema --output-last-message", stderr="")
            if args == ["codex", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="codex 1.0", stderr="")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="Logged in using ChatGPT\n", stderr="")
            if args[:2] == ["/bin/codex", "exec"]:
                last_message = Path(args[args.index("--output-last-message") + 1])
                last_message.parent.mkdir(parents=True, exist_ok=True)
                last_message.write_text("{not-json", encoding="utf-8")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"event":"done"}\n', stderr="")
            raise AssertionError(args)

        def resolver_factory():
            return ReviewProviderResolver(
                which=which,
                runner=runner,
                codex_schema_probe=ReviewProviderProbeCheck("ok", True, "Codex schema proof green"),
                codex_read_only_probe=ReviewProviderProbeCheck("ok", True, "Codex read-only proof green"),
            )

        code, artifact, sidecars = self._run_realish_stage(("codex",), runner=runner, resolver_factory=resolver_factory)

        self.assertEqual(code, 1)
        self.assertEqual(artifact["status"], "error")
        self.assertEqual(artifact["provider_count"], 0)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "codex")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "malformed_output")
        self.assertEqual(sidecars["codex"]["last_message"], "{not-json")

    def test_run_stage_records_real_codex_timeout_as_partial_with_claude_success(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "codex"} else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="-p --permission-mode --output-format --json-schema", stderr="")
            if args == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="--json --sandbox --output-schema --output-last-message", stderr="")
            if args == ["claude", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="claude 1.0", stderr="")
            if args == ["codex", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="codex 1.0", stderr="")
            if args == ["claude", "auth", "status", "--json"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"loggedIn": True}), stderr="")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="Logged in using ChatGPT\n", stderr="")
            if args[:2] == ["/bin/codex", "exec"]:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"], output='{"event":"started"}\n', stderr="slow")
            if args[:2] == ["/bin/claude", "-p"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"findings": []}), stderr="")
            raise AssertionError(args)

        def resolver_factory():
            return ReviewProviderResolver(
                which=which,
                runner=runner,
                claude_read_only_probe=ReviewProviderProbeCheck("ok", True, "Claude read-only proof green"),
                codex_schema_probe=ReviewProviderProbeCheck("ok", True, "Codex schema proof green"),
                codex_read_only_probe=ReviewProviderProbeCheck("ok", True, "Codex read-only proof green"),
            )

        code, artifact, sidecars = self._run_realish_stage(("claude", "codex"), runner=runner, resolver_factory=resolver_factory)

        self.assertEqual(code, 0)
        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "codex")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "timeout")
        self.assertEqual(sidecars["claude"]["meta"]["status"], "ok")
        self.assertEqual(sidecars["codex"]["meta"]["error_class"], "timeout")

    def test_run_stage_runs_real_claude_native_schema_finding_when_r3_and_r4_gates_are_ready(self) -> None:
        finding = {
            "severity": "high",
            "category": "logic",
            "summary": "Rejects valid output",
            "file_path": "py/swarm_do/pipeline/provider_review.py",
            "line_start": 42,
            "line_end": 42,
            "confidence": 0.9,
            "evidence": "schema_ok is false",
            "recommendation": "Preserve valid provider emissions",
        }

        def which(cmd: str) -> str | None:
            return "/bin/claude" if cmd == "claude" else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="-p --permission-mode --output-format --json-schema", stderr="")
            if args == ["claude", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="claude 1.0", stderr="")
            if args == ["claude", "auth", "status", "--json"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"loggedIn": True}), stderr="")
            if args[:2] == ["/bin/claude", "-p"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"result": json.dumps({"findings": [finding]})}), stderr="")
            raise AssertionError(args)

        def resolver_factory():
            return ReviewProviderResolver(
                which=which,
                runner=runner,
                claude_read_only_probe=ReviewProviderProbeCheck("ok", True, "Claude read-only proof green"),
            )

        code, artifact, sidecars = self._run_realish_stage(("claude",), runner=runner, resolver_factory=resolver_factory)

        self.assertEqual(code, 0)
        self.assertEqual(artifact["status"], "ok")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["findings"][0]["detected_by"], ["claude"])
        self.assertEqual(artifact["findings"][0]["summary"], "Rejects valid output")
        self.assertEqual(sidecars["claude"]["meta"]["command_argv"][:5], ["/bin/claude", "-p", "--permission-mode", "plan", "--output-format"])

    def test_run_stage_records_malformed_real_claude_output_without_crashing(self) -> None:
        def which(cmd: str) -> str | None:
            return "/bin/claude" if cmd == "claude" else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="-p --permission-mode --output-format --json-schema", stderr="")
            if args == ["claude", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="claude 1.0", stderr="")
            if args == ["claude", "auth", "status", "--json"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"loggedIn": True}), stderr="")
            if args[:2] == ["/bin/claude", "-p"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="{not-json", stderr="")
            raise AssertionError(args)

        def resolver_factory():
            return ReviewProviderResolver(
                which=which,
                runner=runner,
                claude_read_only_probe=ReviewProviderProbeCheck("ok", True, "Claude read-only proof green"),
            )

        code, artifact, sidecars = self._run_realish_stage(("claude",), runner=runner, resolver_factory=resolver_factory)

        self.assertEqual(code, 1)
        self.assertEqual(artifact["status"], "error")
        self.assertEqual(artifact["provider_errors"][0]["provider"], "claude")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "malformed_output")
        self.assertEqual(sidecars["claude"]["stdout"], "{not-json")

    def test_run_stage_records_real_claude_timeout_as_partial_with_codex_success(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "codex"} else None

        def runner(args, **kwargs):
            if args == ["claude", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="-p --permission-mode --output-format --json-schema", stderr="")
            if args == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="--json --sandbox --output-schema --output-last-message", stderr="")
            if args == ["claude", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="claude 1.0", stderr="")
            if args == ["codex", "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="codex 1.0", stderr="")
            if args == ["claude", "auth", "status", "--json"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"loggedIn": True}), stderr="")
            if args == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="Logged in using ChatGPT\n", stderr="")
            if args[:2] == ["/bin/claude", "-p"]:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="", stderr="slow")
            if args[:2] == ["/bin/codex", "exec"]:
                last_message = Path(args[args.index("--output-last-message") + 1])
                last_message.parent.mkdir(parents=True, exist_ok=True)
                last_message.write_text(json.dumps({"findings": []}), encoding="utf-8")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"event":"done"}\n', stderr="")
            raise AssertionError(args)

        def resolver_factory():
            return ReviewProviderResolver(
                which=which,
                runner=runner,
                claude_read_only_probe=ReviewProviderProbeCheck("ok", True, "Claude read-only proof green"),
                codex_schema_probe=ReviewProviderProbeCheck("ok", True, "Codex schema proof green"),
                codex_read_only_probe=ReviewProviderProbeCheck("ok", True, "Codex read-only proof green"),
            )

        code, artifact, sidecars = self._run_realish_stage(("claude", "codex"), runner=runner, resolver_factory=resolver_factory)

        self.assertEqual(code, 0)
        self.assertEqual(artifact["status"], "partial")
        self.assertEqual(artifact["provider_count"], 1)
        self.assertEqual(artifact["provider_errors"][0]["provider"], "claude")
        self.assertEqual(artifact["provider_errors"][0]["provider_error_class"], "timeout")
        self.assertEqual(sidecars["codex"]["meta"]["status"], "ok")
        self.assertEqual(sidecars["claude"]["meta"]["error_class"], "timeout")

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
