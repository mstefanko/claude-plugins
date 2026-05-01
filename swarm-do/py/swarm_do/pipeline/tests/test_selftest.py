"""Fixture-backed tests for `bin/swarm selftest`."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline import selftest as st


class _IsolatedDataDir:
    def __init__(self) -> None:
        self.tmp: tempfile.TemporaryDirectory | None = None
        self._old: str | None = None
        self._beads_patch = None

    def __enter__(self) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = self.tmp.name
        self._beads_patch = mock.patch("swarm_do.pipeline.beads_health.beads_where", side_effect=_fake_beads_where)
        self._beads_patch.start()
        return Path(self.tmp.name)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._beads_patch is not None:
            self._beads_patch.stop()
        if self._old is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old
        if self.tmp is not None:
            self.tmp.cleanup()


class _FakeBeads:
    def __init__(self, target_repo: Path, ok: bool):
        self.ok = ok
        self.target_repo = str(target_repo)
        self.rig = str(target_repo / ".beads") if ok else None
        self.summary = "Beads rig detected" if ok else "no Beads rig detected in target repo"
        self.remediation = None if ok else "run /swarmdaddy:init-beads in the target repo before launching a swarm run"

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": "pass" if self.ok else "fail",
            "target_repo": self.target_repo,
            "rig": self.rig,
            "summary": self.summary,
            "remediation": self.remediation,
            "details": {},
        }


def _fake_beads_where(target_repo: Path):
    repo = Path(target_repo)
    return _FakeBeads(repo, (repo / ".beads").is_dir())


def _make_target_repo(root: Path, with_beads: bool = True) -> Path:
    repo = root / "target_repo"
    repo.mkdir(parents=True, exist_ok=True)
    if with_beads:
        beads = repo / ".beads"
        beads.mkdir(exist_ok=True)
        (beads / "config.json").write_text("{}\n", encoding="utf-8")
    return repo


def _write_active_run(data_dir: Path, payload: dict) -> Path:
    path = data_dir / "active-run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RedactionTests(unittest.TestCase):
    def test_redacts_github_pat(self) -> None:
        text = "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        self.assertNotIn("ghp_abc", st._redact(text))
        self.assertIn("[REDACTED]", st._redact(text))

    def test_redacts_anthropic_and_openai(self) -> None:
        text = "key sk-ant-xyz12345678901234567890 and sk-1234567890abcdefghij"
        out = st._redact(text)
        self.assertNotIn("sk-ant-xyz", out)
        self.assertNotIn("sk-1234567890", out)

    def test_redacts_aws_access_key(self) -> None:
        out = st._redact("AKIAABCDEFGHIJ1234567 reused")
        self.assertNotIn("AKIAABCDEFGHIJ1234567", out)

    def test_redacts_password_token_pairs(self) -> None:
        out = st._redact('password=hunter2 token=abc api_key=zzz Authorization=BearerXYZ')
        self.assertNotIn("hunter2", out)
        self.assertNotIn("BearerXYZ", out)

    def test_redact_value_walks_nested(self) -> None:
        out = st.redact_value({"a": ["password=hunter2", {"k": "ok"}], "b": ("ghp_" + "x" * 30,)})
        self.assertNotIn("hunter2", json.dumps(out))
        self.assertNotIn("ghp_xxxx", json.dumps(out))


class HealthyFixtureTests(unittest.TestCase):
    def test_healthy_repo_passes_hard_checks(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            report = st.run_selftest(target_repo=target)
            self.assertEqual(report.exit_status, 0, msg=str(report.to_dict()))
            self.assertEqual(report.summary["fail"], 0)
            ids = [c.id for c in report.checks]
            self.assertEqual(set(ids), set(st.HARD_CHECK_IDS) | set(st.ADVISORY_CHECK_IDS))


class HardFailureTests(unittest.TestCase):
    def test_no_beads_rig_hard_fails(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir, with_beads=False)
            report = st.run_selftest(target_repo=target)
            beads = next(c for c in report.checks if c.id == "beads-rig-present")
            self.assertEqual(beads.status, "fail")
            self.assertEqual(beads.severity, "hard")
            self.assertEqual(report.exit_status, 1)
            self.assertGreaterEqual(report.summary["hard_failures"], 1)

    def test_bad_preset_hard_fails(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            report = st.run_selftest(target_repo=target, preset="this-preset-does-not-exist")
            preset_check = next(c for c in report.checks if c.id == "active-preset-loads")
            self.assertEqual(preset_check.status, "fail")
            self.assertEqual(report.exit_status, 1)

    def test_invalid_permission_fragment_hard_fails(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)

            def boom(_data, label="fragment"):
                raise ValueError(f"bad fragment {label}")

            with mock.patch("swarm_do.pipeline.permissions.validate_fragment", side_effect=boom):
                report = st.run_selftest(target_repo=target)
            perms = next(c for c in report.checks if c.id == "role-permissions-load")
            self.assertEqual(perms.status, "fail")
            self.assertEqual(report.exit_status, 1)

    def test_invalid_active_run_hard_fails(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            (data_dir / "active-run.json").write_text("not json", encoding="utf-8")
            report = st.run_selftest(target_repo=target)
            ar = next(c for c in report.checks if c.id == "active-run-valid")
            self.assertEqual(ar.status, "fail")
            self.assertEqual(report.exit_status, 1)

    def test_active_run_missing_keys_hard_fails(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            _write_active_run(data_dir, {"schema_version": 1})
            report = st.run_selftest(target_repo=target)
            ar = next(c for c in report.checks if c.id == "active-run-valid")
            self.assertEqual(ar.status, "fail")
            self.assertIn("missing", ar.summary)


class AdvisoryWarningTests(unittest.TestCase):
    def test_stale_active_run_warns_but_does_not_fail(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            path = _write_active_run(data_dir, {
                "schema_version": 1,
                "run_id": "01TEST",
                "status": "incomplete",
            })
            old = (Path(__file__).stat().st_mtime) - (st.ACTIVE_RUN_FRESH_WARN_SECONDS + 60)
            os.utime(path, (old, old))
            report = st.run_selftest(target_repo=target)
            ar = next(c for c in report.checks if c.id == "active-run-fresh")
            self.assertEqual(ar.status, "warn")
            self.assertEqual(ar.severity, "advisory")
            self.assertEqual(report.exit_status, 0)
            self.assertGreaterEqual(report.summary["advisory_warnings"], 1)

    def test_strict_upgrades_advisory_warning_to_exit_1(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            path = _write_active_run(data_dir, {
                "schema_version": 1,
                "run_id": "01TEST",
                "status": "incomplete",
            })
            old = (Path(__file__).stat().st_mtime) - (st.ACTIVE_RUN_FRESH_WARN_SECONDS + 60)
            os.utime(path, (old, old))
            report = st.run_selftest(target_repo=target, strict=True)
            self.assertEqual(report.exit_status, 1)
            ar = next(c for c in report.checks if c.id == "active-run-fresh")
            self.assertEqual(ar.severity, "advisory", "severity must remain advisory under --strict")
            self.assertEqual(ar.status, "warn")

    def test_provider_doctor_warning_is_advisory(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)

            class FakeReport:
                ok = False

                def as_dict(self):
                    return {"checks": [{"provider": "claude"}]}

            with mock.patch(
                "swarm_do.pipeline.providers.provider_doctor",
                return_value=FakeReport(),
            ):
                report = st.run_selftest(target_repo=target)
            pd = next(c for c in report.checks if c.id == "provider-doctor")
            self.assertEqual(pd.severity, "advisory")
            self.assertEqual(pd.status, "warn")
            self.assertEqual(report.exit_status, 0)

            with mock.patch(
                "swarm_do.pipeline.providers.provider_doctor",
                return_value=FakeReport(),
            ):
                strict = st.run_selftest(target_repo=target, strict=True)
            self.assertEqual(strict.exit_status, 1)


class JsonShapeTests(unittest.TestCase):
    def test_json_shape_omits_contract_sentinel(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            payload = json.loads(st.format_json(st.run_selftest(target_repo=target)))
        self.assertNotIn("_contract", payload)
        for key in ("schema_version", "summary", "checks", "exit_status", "strict"):
            self.assertIn(key, payload)
        for check in payload["checks"]:
            self.assertEqual(set(check.keys()), {"id", "severity", "status", "summary", "details", "remediation"})
            self.assertIn(check["status"], {"pass", "warn", "fail"})

    def test_summary_counts_match_checks(self) -> None:
        with _IsolatedDataDir() as data_dir:
            target = _make_target_repo(data_dir)
            report = st.run_selftest(target_repo=target)
        total = report.summary["total"]
        self.assertEqual(total, len(report.checks))
        derived = report.summary["pass"] + report.summary["warn"] + report.summary["fail"]
        self.assertEqual(total, derived)


if __name__ == "__main__":
    unittest.main()
