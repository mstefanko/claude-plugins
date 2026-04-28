# test_prepare_artifact

"""Coverage for the prepared_plan.v1 artifact contract (Phase 1).

Maps to acceptance criteria 1-12 in
``swarm-do/.../work_units/phase-1-bootstrap.json`` and the work-breakdown
in analysis bead mstefanko-plugins-6v1.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline import prepare
from swarm_do.pipeline.prepare import (
    InvalidPreparedTransition,
    STATUS_ACCEPTED,
    STATUS_DRAFT,
    STATUS_NEEDS_INPUT,
    STATUS_READY,
    STATUS_REJECTED,
    StaleReason,
    _compute_cache_key,
    _sha256_bytes,
    _sha256_file,
    accept_prepared,
    canonicalize,
    check_stale,
    load_prepared_artifact,
    mark_ready_for_acceptance,
    reject_prepared,
    write_prepared_artifact,
)


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def _git_init_repo(repo_root: Path) -> str:
    """Initialize a tiny git repo and return the HEAD sha."""

    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo_root), check=True, env=env)
    (repo_root / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_root), check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=str(repo_root), check=True, env=env
    )
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root), check=True, capture_output=True, text=True, env=env,
    )
    return out.stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Materialize a tiny repo with a source plan and prepared sidecar.

    Returns (repo_root, source_plan_sha, prepared_plan_sha, git_base_sha).
    """

    repo = tmp_path / "repo"
    repo.mkdir()
    git_base_sha = _git_init_repo(repo)

    source = repo / "plan.md"
    source.write_text("### Phase 1: Tiny\n- Update README.\n", encoding="utf-8")
    prepared = repo / "prepared.md"
    prepared.write_text("# prepared\n", encoding="utf-8")
    inspect = repo / "inspect.json"
    inspect.write_text("{}\n", encoding="utf-8")
    sidecar = repo / "phase-1.work_units.json"
    sidecar.write_text("{\"work_units\": []}\n", encoding="utf-8")

    return repo, _sha256_file(source), _sha256_file(prepared), git_base_sha


def _phase_entry(
    *, phase_id: str, content_sha: str, plan_context_sha: str, prepared_plan_sha: str
) -> dict:
    return {
        "phase_id": phase_id,
        "title": "Tiny",
        "complexity": "simple",
        "kind": "docs",
        "content_sha": content_sha,
        "plan_context_sha": plan_context_sha,
        "cache_key": _compute_cache_key(
            content_sha=content_sha,
            prepared_plan_sha=prepared_plan_sha,
            plan_context_sha=plan_context_sha,
        ),
        "requires_decomposition": False,
    }


def _minimal_payload(
    *, run_id: str, repo_root: Path, source_plan_sha: str,
    prepared_plan_sha: str, git_base_sha: str,
) -> dict:
    plan_text = (repo_root / "plan.md").read_text(encoding="utf-8")
    inspect_sha = _sha256_file(repo_root / "inspect.json")
    sidecar_sha = _sha256_file(repo_root / "phase-1.work_units.json")
    content_sha = _sha256_bytes(plan_text.encode("utf-8"))
    plan_context_sha = _sha256_bytes(b"phase-1-context")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "repo_root": str(repo_root),
        "git_base_ref": "HEAD",
        "git_base_sha": git_base_sha,
        "source_plan_path": "plan.md",
        "source_plan_sha": source_plan_sha,
        "prepared_plan_path": "prepared.md",
        "prepared_plan_sha": prepared_plan_sha,
        "inspect_artifact": {"path": "inspect.json", "sha": inspect_sha},
        "phase_map": [
            _phase_entry(
                phase_id="phase-1",
                content_sha=content_sha,
                plan_context_sha=plan_context_sha,
                prepared_plan_sha=prepared_plan_sha,
            )
        ],
        "review_findings": [],
        "review_iteration_count": 0,
        "accepted_fixes": [],
        "work_unit_artifacts": {
            "phase-1": {"path": "phase-1.work_units.json", "sha": sidecar_sha},
        },
        "acceptance": None,
        "status": STATUS_DRAFT,
        "created_at": "2026-04-27T00:00:00Z",
        "ready_at": None,
        "accepted_at": None,
    }


def _read_run_events(data_dir: Path) -> list[dict]:
    path = data_dir / "telemetry" / "run_events.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _assert_run_events_validate(test: unittest.TestCase, events: list[dict]) -> None:
    from swarm_do.telemetry.schemas import load_schema, validate_value

    schema = load_schema("run_events")
    for event in events:
        test.assertEqual(validate_value(event, schema), [], msg=event)


class CanonicalizeTests(unittest.TestCase):
    def test_relative_path_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "swarm-do").mkdir()
            result = canonicalize("swarm-do/plan.md", repo_root=root)
            self.assertEqual(result, Path("swarm-do/plan.md"))

    def test_absolute_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                canonicalize("/etc/passwd", repo_root=Path(td))

    def test_dotdot_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                canonicalize("../escape.md", repo_root=Path(td))

    def test_out_of_repo_resolved_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                # No literal ".." but resolves outside repo via symlink-style escape.
                canonicalize("inner/../../escape", repo_root=Path(td))

    def test_empty_string_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                canonicalize("", repo_root=Path(td))


class WriteLoadRoundTripTests(unittest.TestCase):
    def test_write_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            path = write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
            self.assertTrue(path.is_file())
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["run_id"], RUN_ID)
            self.assertEqual(loaded["status"], STATUS_DRAFT)

    def test_load_missing_artifact_raises_filenotfound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                load_prepared_artifact(RUN_ID, data_dir=Path(td), repo_root=Path(td))

    def test_load_rejects_bad_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["status"] = "bogus"
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)

    def test_load_rejects_review_iteration_count_4(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["review_iteration_count"] = 4
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)

    def test_load_rejects_negative_review_iteration_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["review_iteration_count"] = -1
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)

    def test_load_rejects_work_unit_artifacts_unknown_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["work_unit_artifacts"]["phase-99"] = {
                "path": "ghost.json",
                "sha": "0" * 64,
            }
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)

    def test_load_rejects_path_with_dotdot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["source_plan_path"] = "../escape.md"
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)

    def test_load_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["source_plan_path"] = "/etc/passwd"
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)

    def test_load_rejects_bad_sha_format(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID, repo_root=repo,
                source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            payload["source_plan_sha"] = "ZZZ"
            with self.assertRaises(ValueError):
                write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)


class StateTransitionTests(unittest.TestCase):
    def _bootstrap(self, td: Path) -> tuple[Path, Path, dict]:
        repo, src_sha, prep_sha, base_sha = _make_repo(td)
        data = td / "data"
        payload = _minimal_payload(
            run_id=RUN_ID, repo_root=repo,
            source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
            git_base_sha=base_sha,
        )
        write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
        return repo, data, payload

    def test_mark_ready_for_acceptance_from_draft_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_READY)
            self.assertIsNotNone(loaded["ready_at"])

    def test_mark_ready_for_acceptance_from_needs_input_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, payload = self._bootstrap(Path(td))
            payload["status"] = STATUS_NEEDS_INPUT
            write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_READY)

    def test_mark_ready_for_acceptance_from_accepted_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, payload = self._bootstrap(Path(td))
            payload["status"] = STATUS_ACCEPTED
            payload["accepted_at"] = "2026-04-27T00:00:01Z"
            payload["acceptance"] = {
                "accepted_by": "h",
                "accepted_at": "2026-04-27T00:00:01Z",
                "accepted_source_sha": payload["source_plan_sha"],
                "accepted_prepared_sha": payload["prepared_plan_sha"],
            }
            write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
            with self.assertRaises(InvalidPreparedTransition):
                mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)

    def test_accept_prepared_only_from_ready_for_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            with self.assertRaises(InvalidPreparedTransition) as ctx:
                accept_prepared(RUN_ID, data_dir=data, repo_root=repo)
            # AC: error message must include current status string.
            self.assertIn(STATUS_DRAFT, str(ctx.exception))

    def test_accept_prepared_error_uses_invalid_prepared_transition_subclass(self) -> None:
        # InvalidPreparedTransition must be a ValueError subclass so callers
        # using broad except continue to handle it (Phase 1 coordinator Q4).
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            with self.assertRaises(ValueError):
                accept_prepared(RUN_ID, data_dir=data, repo_root=repo)

    def test_accept_prepared_runs_stale_check(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            # Mutate source plan on disk so cache_key drifts.
            (repo / "plan.md").write_text("### Phase 1: Tiny\n- Mutated.\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                accept_prepared(RUN_ID, data_dir=data, repo_root=repo)

    def test_accept_prepared_sets_acceptance_object(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            accept_prepared(RUN_ID, data_dir=data, accepted_by="alice", repo_root=repo)
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_ACCEPTED)
            self.assertIsNotNone(loaded["accepted_at"])
            self.assertEqual(loaded["acceptance"]["accepted_by"], "alice")
            self.assertEqual(
                loaded["acceptance"]["accepted_source_sha"], loaded["source_plan_sha"]
            )

    def test_reject_prepared_from_draft(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            reject_prepared(RUN_ID, reason="no", data_dir=data, repo_root=repo)
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_REJECTED)

    def test_reject_prepared_from_ready_for_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            reject_prepared(RUN_ID, data_dir=data, repo_root=repo)
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_REJECTED)

    def test_reject_prepared_from_accepted_is_idempotent_noop(self) -> None:
        # Phase 1 coordinator decision Q3: from accepted/rejected, reject is
        # an idempotent no-op (returns the existing artifact path, does not
        # raise). This avoids racing rejections after a successful accept.
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            accept_prepared(RUN_ID, data_dir=data, repo_root=repo)
            path = reject_prepared(RUN_ID, data_dir=data, repo_root=repo)
            self.assertTrue(path.is_file())
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_ACCEPTED)

    def test_reject_prepared_from_rejected_is_idempotent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, _ = self._bootstrap(Path(td))
            reject_prepared(RUN_ID, data_dir=data, repo_root=repo)
            # Second reject must not raise; status stays rejected.
            reject_prepared(RUN_ID, data_dir=data, repo_root=repo)
            loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
            self.assertEqual(loaded["status"], STATUS_REJECTED)

    def test_prepare_module_has_no_force_accept_helper(self) -> None:
        # AC #7: accepted is reachable ONLY via accept_prepared.
        self.assertFalse(hasattr(prepare, "force_accept"))
        self.assertFalse(hasattr(prepare, "force_accepted"))


class StaleDetectionTests(unittest.TestCase):
    def _ready_setup(self, td: Path) -> tuple[Path, Path, dict]:
        repo, src_sha, prep_sha, base_sha = _make_repo(td)
        data = td / "data"
        payload = _minimal_payload(
            run_id=RUN_ID, repo_root=repo,
            source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
            git_base_sha=base_sha,
        )
        write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
        mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
        loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
        return repo, data, loaded

    def test_no_drift_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, _, loaded = self._ready_setup(Path(td))
            self.assertIsNone(check_stale(loaded, repo_root=repo))

    def test_whole_plan_sha_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, _, loaded = self._ready_setup(Path(td))
            (repo / "plan.md").write_text("mutated\n", encoding="utf-8")
            result = check_stale(loaded, repo_root=repo)
            self.assertIsNotNone(result)
            self.assertIn("source_plan_sha", result.reasons)

    def test_sidecar_sha_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, _, loaded = self._ready_setup(Path(td))
            (repo / "prepared.md").write_text("mutated\n", encoding="utf-8")
            result = check_stale(loaded, repo_root=repo)
            self.assertIsNotNone(result)
            self.assertIn("prepared_plan_sha", result.reasons)

    def test_git_base_sha_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, _, loaded = self._ready_setup(Path(td))
            mutated = dict(loaded)
            mutated["git_base_sha"] = "0" * 40
            result = check_stale(mutated, repo_root=repo)
            self.assertIsNotNone(result)
            self.assertIn("git_base_sha", result.reasons)

    def test_per_phase_cache_key_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, _, loaded = self._ready_setup(Path(td))
            (repo / "plan.md").write_text("entirely-different\n", encoding="utf-8")
            result = check_stale(loaded, repo_root=repo)
            self.assertIsNotNone(result)
            self.assertTrue(any(r.startswith("phase:") for r in result.reasons))

    def test_stale_reason_is_frozen_dataclass(self) -> None:
        sr = StaleReason(reasons=("a", "b"))
        with self.assertRaises(Exception):
            sr.reasons = ("c",)  # type: ignore[misc]


class PrepareTelemetryEventTests(unittest.TestCase):
    def test_prepare_run_emits_valid_ready_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = tmp / "repo"
            repo.mkdir()
            (repo / "README.md").write_text("# Test\n", encoding="utf-8")
            (repo / "plan.md").write_text(
                "### Phase 1: Docs (complexity: simple, kind: docs)\n\n"
                "### File Targets\n\n"
                "- `README.md`\n\n"
                "### Acceptance Criteria\n\n"
                "- README is updated.\n\n"
                "### Verification Commands\n\n"
                "```\ntrue\n```\n",
                encoding="utf-8",
            )
            data = tmp / "data"

            prepare.prepare_plan_run("plan.md", repo_root=repo, data_dir=data, run_id=RUN_ID)

            events = _read_run_events(data)
            _assert_run_events_validate(self, events)
            event_types = [event["event_type"] for event in events]
            for event_type in (
                "prepare_started",
                "prepare_lint_findings",
                "prepare_review_findings",
                "prepare_safe_fixes_accepted",
                "prepare_safe_fixes_proposed_unaccepted",
                "prepare_ready_for_acceptance",
            ):
                self.assertIn(event_type, event_types)
            self.assertNotIn("prepare_blocking_findings", event_types)

    def test_prepare_run_emits_valid_blocking_findings_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = tmp / "repo"
            repo.mkdir()
            (repo / "plan.md").write_text(
                "### Phase 1: Docs (complexity: simple, kind: docs)\n\n"
                "### File Targets\n\n"
                "- `README.md`\n\n"
                "### Implementation\n\n"
                "- Update the README.\n",
                encoding="utf-8",
            )
            data = tmp / "data"

            result = prepare.prepare_plan_run("plan.md", repo_root=repo, data_dir=data, run_id=RUN_ID)

            self.assertEqual(result.status, STATUS_NEEDS_INPUT)
            events = _read_run_events(data)
            _assert_run_events_validate(self, events)
            self.assertIn("prepare_blocking_findings", [event["event_type"] for event in events])

    def test_accept_and_dispatch_emit_valid_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = tmp / "repo"
            repo.mkdir()
            _git_init_repo(repo)
            (repo / "README.md").write_text("# Test\n", encoding="utf-8")
            (repo / "plan.md").write_text(
                "### Phase 1: Docs (complexity: simple, kind: docs)\n\n"
                "### File Targets\n\n"
                "- `README.md`\n\n"
                "### Acceptance Criteria\n\n"
                "- README is updated.\n\n"
                "### Verification Commands\n\n"
                "```\ntrue\n```\n",
                encoding="utf-8",
            )
            data = tmp / "data"

            prepare.prepare_plan_run("plan.md", repo_root=repo, data_dir=data, run_id=RUN_ID)
            prepare.accept_prepared(RUN_ID, data_dir=data, repo_root=repo)
            prepare.verify_prepared_for_dispatch(RUN_ID, data_dir=data, repo_root=repo)

            events = _read_run_events(data)
            _assert_run_events_validate(self, events)
            event_types = [event["event_type"] for event in events]
            self.assertIn("prepare_accepted", event_types)
            self.assertIn("prepare_dispatch_started", event_types)

    def test_stale_accept_rejection_emits_valid_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo, src_sha, prep_sha, base_sha = _make_repo(tmp)
            data = tmp / "data"
            payload = _minimal_payload(
                run_id=RUN_ID,
                repo_root=repo,
                source_plan_sha=src_sha,
                prepared_plan_sha=prep_sha,
                git_base_sha=base_sha,
            )
            write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
            mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
            (repo / "plan.md").write_text("### Phase 1: Tiny\n- Mutated.\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                accept_prepared(RUN_ID, data_dir=data, repo_root=repo)

            events = _read_run_events(data)
            _assert_run_events_validate(self, events)
            stale_events = [
                event for event in events if event["event_type"] == "prepare_stale_rejected"
            ]
            self.assertEqual(len(stale_events), 1)
            self.assertIn("source_plan_sha", stale_events[0]["details"]["stale_reasons"])


class CliSubcommandTests(unittest.TestCase):
    """Drive cmd_plan directly as the work breakdown specifies."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_root = Path(self._tmp.name)
        self._old_cpd = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self._tmp_root / "data")

    def tearDown(self) -> None:
        if self._old_cpd is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old_cpd
        self._tmp.cleanup()

    def _bootstrap_ready(self) -> tuple[Path, Path]:
        repo, src_sha, prep_sha, base_sha = _make_repo(self._tmp_root)
        data = Path(os.environ["CLAUDE_PLUGIN_DATA"])
        payload = _minimal_payload(
            run_id=RUN_ID, repo_root=repo,
            source_plan_sha=src_sha, prepared_plan_sha=prep_sha,
            git_base_sha=base_sha,
        )
        write_prepared_artifact(run_id=RUN_ID, payload=payload, data_dir=data)
        mark_ready_for_acceptance(RUN_ID, data_dir=data, repo_root=repo)
        return repo, data

    def test_plan_accept_subcommand_dispatches(self) -> None:
        from swarm_do.pipeline.cli import cmd_plan

        repo, data = self._bootstrap_ready()
        # Patch resolve_data_dir for prepare module so artifact reads/writes use temp dir.
        with mock.patch("swarm_do.pipeline.prepare.resolve_data_dir", return_value=data),              mock.patch("swarm_do.pipeline.prepare.REPO_ROOT", repo):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_plan(argparse.Namespace(
                    plan_command="accept",
                    run_id=RUN_ID,
                    accepted_by="cli-tester",
                    json=True,
                ))
            self.assertEqual(rc, 0)
            output = json.loads(buf.getvalue())
            self.assertEqual(output["status"], "accepted")
            self.assertEqual(output["run_id"], RUN_ID)

    def test_plan_reject_subcommand_dispatches(self) -> None:
        from swarm_do.pipeline.cli import cmd_plan

        repo, data = self._bootstrap_ready()
        with mock.patch("swarm_do.pipeline.prepare.resolve_data_dir", return_value=data),              mock.patch("swarm_do.pipeline.prepare.REPO_ROOT", repo):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_plan(argparse.Namespace(
                    plan_command="reject",
                    run_id=RUN_ID,
                    reason="dropping",
                    json=True,
                ))
            self.assertEqual(rc, 0)
            output = json.loads(buf.getvalue())
            self.assertEqual(output["status"], "rejected")

    def test_plan_inspect_unchanged_regression(self) -> None:
        # Drive cmd_plan with the existing inspect contract; assert the JSON
        # shape contains the stable keys we promised. (AC #8)
        from swarm_do.pipeline.cli import cmd_plan

        plan = self._tmp_root / "regress.md"
        plan.write_text("### Phase 1: Tiny (complexity: simple)\n- Update README.\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_plan(argparse.Namespace(
                plan_command="inspect",
                plan_path=str(plan),
                phase=None,
                json=True,
                no_write=True,
            ))
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("reports", payload)
        for report in payload["reports"]:
            for key in ("phase_id", "complexity", "requires_decomposition"):
                self.assertIn(key, report)


class BeadsIndependenceTests(unittest.TestCase):
    def test_prepare_module_does_not_import_bd(self) -> None:
        src = Path(prepare.__file__).read_text(encoding="utf-8")
        # Strict: no bd imports of any flavor.
        for line in src.splitlines():
            stripped = line.lstrip()
            self.assertFalse(
                stripped.startswith("import bd") or stripped.startswith("from bd "),
                f"prepare.py must not import bd; offending line: {line!r}",
            )


if __name__ == "__main__":
    unittest.main()
