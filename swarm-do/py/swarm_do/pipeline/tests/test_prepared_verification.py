from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.prepare import (
    load_prepared_artifact,
    verify_prepared_payload,
    verify_prepared_run,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PreparedVerificationTests(unittest.TestCase):
    def test_rejects_work_unit_sidecar_with_mismatched_git_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            payload = load_prepared_artifact(run_id, data_dir=data, repo_root=repo)
            descriptor = payload["work_unit_artifacts"]["1"]
            sidecar_path = repo / descriptor["path"]
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["git_base_sha"] = "b" * 40
            sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            descriptor["artifact"] = sidecar
            descriptor["sha"] = _sha256_file(sidecar_path)

            with self.assertRaisesRegex(ValueError, "does not match run git_base_sha"):
                verify_prepared_payload(payload, repo_root=repo)

    def test_rejects_zero_git_base_before_sidecar_checks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            payload = load_prepared_artifact(run_id, data_dir=data, repo_root=repo)
            payload = copy.deepcopy(payload)
            payload["git_base_sha"] = "0" * 40

            with self.assertRaisesRegex(ValueError, "zero placeholder"):
                verify_prepared_payload(payload, repo_root=repo)

    def test_verify_prepared_run_does_not_emit_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            events_path = data / "telemetry" / "run_events.jsonl"
            before = events_path.read_text(encoding="utf-8") if events_path.is_file() else ""

            verified = verify_prepared_run(run_id, data_dir=data, repo_root=repo)

            after = events_path.read_text(encoding="utf-8") if events_path.is_file() else ""
            self.assertEqual(verified.run_id, run_id)
            self.assertEqual(after, before)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
