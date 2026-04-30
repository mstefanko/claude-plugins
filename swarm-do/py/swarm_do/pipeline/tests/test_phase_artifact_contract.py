from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.phase_artifact_contract import phase_artifact_contract_markdown
from swarm_do.pipeline.phase_pump import _append_claude_print_contract
from swarm_do.pipeline.phase_sessions import (
    PhaseArtifactContractError,
    claim_next_phase,
    init_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_session_path,
    start_phase,
    validate_phase_artifacts,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run
from swarm_do.telemetry.schemas import validate_value


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
PREPARED_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PHASE_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
EXAMPLES = REPO_ROOT / "docs" / "examples" / "phase-artifacts"


class PhaseArtifactContractTests(unittest.TestCase):
    def test_docs_examples_validate_against_schemas(self) -> None:
        result_schema = json.loads((REPO_ROOT / "schemas" / "phase_result.schema.json").read_text(encoding="utf-8"))
        handoff_schema = json.loads((REPO_ROOT / "schemas" / "phase_handoff.schema.json").read_text(encoding="utf-8"))
        for path in sorted(EXAMPLES.glob("*.result.json")):
            with self.subTest(path=path.name):
                errors = validate_value(json.loads(path.read_text(encoding="utf-8")), result_schema)
                self.assertEqual(errors, [])
        for path in sorted(EXAMPLES.glob("*.handoff.json")):
            with self.subTest(path=path.name):
                errors = validate_value(json.loads(path.read_text(encoding="utf-8")), handoff_schema)
                self.assertEqual(errors, [])

    def test_docs_example_pairs_are_full_contract_valid(self) -> None:
        pairs = (
            ("complete.result.json", "complete.handoff.json"),
            ("failed-retryable.result.json", "failed-retryable.handoff.json"),
            ("blocked.result.json", "blocked.handoff.json"),
            ("needs-input.result.json", "needs-input.handoff.json"),
        )
        for result_name, handoff_name in pairs:
            with self.subTest(result=result_name):
                with tempfile.TemporaryDirectory() as td:
                    result_path, handoff_path = _copy_example_pair_into_phase_session_run(
                        Path(td),
                        result_name,
                        handoff_name,
                    )
                    self.assertTrue(result_path.is_file())
                    self.assertTrue(handoff_path.is_file())

    def test_contract_markdown_contains_statuses_and_array_rules(self) -> None:
        text = phase_artifact_contract_markdown(
            result_path="/tmp/result.json",
            handoff_path="/tmp/handoff.json",
            run_id=RUN_ID,
            phase_id="1",
            phase_attempt=1,
            launcher="claude-print",
            session_name="session",
            prepared_plan_sha=PREPARED_SHA,
            phase_content_sha=PHASE_SHA,
        )

        for status in ("complete", "failed", "blocked", "needs_input"):
            self.assertIn(status, text)
        self.assertIn("handoff.decisions", text)
        self.assertIn("plain string", text)

    def test_launcher_contract_uses_shared_text_and_exact_paths(self) -> None:
        text = _append_claude_print_contract(
            "base prompt",
            result_path=Path("/tmp/result.json"),
            handoff_path=Path("/tmp/handoff.json"),
            status_values=["complete", "failed", "blocked", "needs_input"],
            run_id=RUN_ID,
            phase_id="1",
            phase_attempt=1,
            session_name="session",
            prepared_plan_sha=PREPARED_SHA,
            phase_content_sha=PHASE_SHA,
        )

        self.assertIn("Write the phase result JSON exactly to: /tmp/result.json", text)
        self.assertIn("Write the phase handoff JSON exactly to: /tmp/handoff.json", text)
        self.assertEqual(text.count("Phase result JSON template:"), 1)
        self.assertIn("## Tool Usage", text)

    def test_negative_contract_failures_keep_kind_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result_path, _ = _copy_example_pair_into_phase_session_run(Path(td), "complete.result.json", "complete.handoff.json")
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            payload["run_id"] = "01BRZ3NDEKTSV4RRFFQ69G5FAV"
            result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaises(PhaseArtifactContractError) as ctx:
                validate_phase_artifacts(RUN_ID, "1", json_file=result_path, expected_status=None, data_dir=Path(td) / "data")
            self.assertEqual(ctx.exception.kind, "result_identity_mismatch")

    def test_object_values_inside_handoff_string_arrays_fail_schema(self) -> None:
        payload = json.loads((EXAMPLES / "complete.handoff.json").read_text(encoding="utf-8"))
        payload["decisions"] = [{"text": "not allowed"}]
        schema = json.loads((REPO_ROOT / "schemas" / "phase_handoff.schema.json").read_text(encoding="utf-8"))

        errors = validate_value(payload, schema)

        self.assertTrue(any("decisions" in error for error in errors))


def _copy_example_pair_into_phase_session_run(
    tmp_path: Path,
    result_name: str,
    handoff_name: str,
) -> tuple[Path, Path]:
    repo, data, run_id = make_prepared_run(tmp_path, run_id=RUN_ID, phase_count=1)
    init_phase_sessions(run_id, data_dir=data, repo_root=repo)
    claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
    start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
    state_path = phase_session_path(run_id, data_dir=data)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["prepared_plan_sha"] = PREPARED_SHA
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    prepared["prepared_plan_sha"] = PREPARED_SHA
    prepared["phase_map"][0]["content_sha"] = PHASE_SHA
    prepared_path.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path = phase_result_path(run_id, "1", 1, data_dir=data)
    handoff_path = phase_handoff_path(run_id, "1", 1, data_dir=data)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXAMPLES / result_name, result_path)
    shutil.copy2(EXAMPLES / handoff_name, handoff_path)
    validate_phase_artifacts(run_id, "1", json_file=result_path, expected_status=None, data_dir=data)
    return result_path, handoff_path


if __name__ == "__main__":
    unittest.main()
