from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.providers import format_provider_report, provider_doctor


def _restore_env(name: str, old: str | None) -> None:
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


class ProviderDoctorTests(unittest.TestCase):
    def test_default_pipeline_checks_only_required_local_backend(self) -> None:
        old = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(which=lambda cmd: f"/bin/{cmd}" if cmd == "claude" else None)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old)

        self.assertTrue(report.ok)
        self.assertEqual(report.pipeline_name, "default")
        self.assertEqual(report.required_backends, ("claude",))
        rendered = format_provider_report(report)
        self.assertIn("OK      backend:claude", rendered)
        self.assertIn("SKIPPED provider:mco", rendered)

    def test_active_hybrid_preset_requires_codex_cli(self) -> None:
        old = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "current-preset.txt").write_text("hybrid-review\n", encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(which=lambda cmd: "/bin/claude" if cmd == "claude" else None)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old)

        self.assertFalse(report.ok)
        self.assertEqual(report.required_backends, ("claude", "codex"))
        self.assertTrue(any(check.name == "backend:codex" and check.status == "error" for check in report.checks))

    def test_active_mco_lab_requires_mco_provider_doctor(self) -> None:
        old = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "current-preset.txt").write_text("mco-review-lab\n", encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(which=lambda cmd: "/bin/claude" if cmd == "claude" else None)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old)

        self.assertFalse(report.ok)
        self.assertEqual(report.required_backends, ("claude",))
        self.assertEqual(report.required_providers, ("mco",))
        self.assertTrue(any(check.name == "provider:mco" and check.status == "error" for check in report.checks))

    def test_mco_doctor_json_passthrough(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "mco"} else None

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout=json.dumps({"providers": [{"name": "codex", "status": "ok"}]}),
                stderr="",
            )

        old = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(run_mco=True, which=which, runner=runner)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old)

        self.assertTrue(report.ok)
        mco = next(check for check in report.checks if check.name == "provider:mco")
        self.assertEqual(mco.status, "ok")
        self.assertEqual(mco.data["payload"]["providers"][0]["name"], "codex")

    def test_mco_stage_fails_when_selected_provider_is_not_ready(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "mco"} else None

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout=json.dumps(
                    {
                        "overall_ok": False,
                        "providers": {
                            "claude": {"ready": False, "reason": "auth_check_failed"},
                            "codex": {"ready": True, "reason": "ok"},
                        },
                    }
                ),
                stderr="",
            )

        old = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "current-preset.txt").write_text("mco-review-lab\n", encoding="utf-8")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(which=which, runner=runner)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old)

        self.assertFalse(report.ok)
        mco = next(check for check in report.checks if check.name == "provider:mco")
        self.assertEqual(mco.status, "error")
        self.assertIn("claude=auth_check_failed", mco.detail)

    def test_mco_malformed_json_fails_closed(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "mco"} else None

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="{not-json", stderr="")

        old = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(run_mco=True, which=which, runner=runner)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old)

        self.assertFalse(report.ok)
        self.assertTrue(any(check.name == "provider:mco" and check.status == "error" for check in report.checks))

    def test_review_doctor_reports_fake_internal_provider_selection(self) -> None:
        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        old_fake = os.environ.get("SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            os.environ["SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS"] = "claude,codex"
            try:
                report = provider_doctor(
                    run_review=True,
                    which=lambda cmd: f"/bin/{cmd}" if cmd == "claude" else None,
                )
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old_data)
                _restore_env("SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS", old_fake)

        self.assertTrue(report.ok)
        payload = report.as_dict()
        self.assertTrue(payload["review_required"])
        self.assertEqual(payload["selected_review_providers"], ["claude", "codex"])
        rendered = format_provider_report(report)
        self.assertIn("provider-review:claude", rendered)
        self.assertIn("selected: claude, codex", rendered)

    def test_review_doctor_json_reports_exact_review_cli_flags(self) -> None:
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
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                report = provider_doctor(run_review=True, which=which, runner=runner)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old_data)

        payload = report.as_dict()
        self.assertEqual(payload["review_schema_flags"]["claude"], ["-p", "--json-schema", "--output-format"])
        self.assertEqual(payload["review_read_only_flags"]["claude"], ["--permission-mode"])
        self.assertEqual(payload["review_schema_flags"]["codex"], ["--json", "--output-schema", "--output-last-message"])
        self.assertEqual(payload["review_read_only_flags"]["codex"], ["--sandbox"])
        self.assertEqual(payload["review_schema_modes"]["codex"], "native")
        self.assertEqual(payload["review_read_only_modes"]["codex"], "flag-detected")
        self.assertEqual(payload["review_missing_schema_flags"]["codex"], [])
        self.assertEqual(payload["selected_review_providers"], [])

    def test_review_and_mco_doctor_contracts_can_be_combined(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/bin/{cmd}" if cmd in {"claude", "mco"} else None

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout=json.dumps({"providers": [{"name": "claude", "status": "ok"}]}),
                stderr="",
            )

        old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        old_fake = os.environ.get("SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            os.environ["SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS"] = "claude"
            try:
                report = provider_doctor(run_review=True, run_mco=True, which=which, runner=runner)
            finally:
                _restore_env("CLAUDE_PLUGIN_DATA", old_data)
                _restore_env("SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS", old_fake)

        self.assertTrue(report.ok)
        self.assertTrue(any(check.name == "provider:mco" and check.status == "ok" for check in report.checks))
        self.assertTrue(any(check.name == "provider-review:claude" and check.status == "ok" for check in report.checks))


if __name__ == "__main__":
    unittest.main()
