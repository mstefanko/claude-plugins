from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path

from swarm_do.pipeline.domain import (
    DOCTOR_FINDING_SEVERITIES,
    PHASE_STATUSES,
    DomainContractError,
    DoctorFinding,
    PhaseAttemptRecord,
    PhaseRecord,
    PhaseStatusReport,
)
from swarm_do.pipeline.paths import REPO_ROOT


PIPELINE_ROOT = REPO_ROOT / "py" / "swarm_do" / "pipeline"


class DomainContractTests(unittest.TestCase):
    def test_phase_record_round_trips_and_rejects_unknown_keys(self) -> None:
        payload = {
            "phase_id": "p1",
            "phase_index": 0,
            "title": "Phase",
            "depends_on_phase_ids": [],
            "status": "running",
            "attempt": 1,
            "lease_owner": "owner",
            "failure_category": "lifecycle",
            "policy_inputs": {"attempt": 1},
            "attempt_history": [],
        }

        record = PhaseRecord.from_mapping(payload)
        self.assertEqual(record.to_dict(), payload)
        self.assertEqual(dataclasses.replace(record, status="failed").to_dict()["status"], "failed")
        with self.assertRaisesRegex(DomainContractError, "unknown"):
            PhaseRecord.from_mapping({**payload, "surprise": True})

    def test_phase_status_enum_accepts_known_values(self) -> None:
        for status in PHASE_STATUSES:
            record = PhaseRecord.from_mapping({"phase_id": "p1", "status": status, "attempt": 0})
            self.assertEqual(record.status, status)
        with self.assertRaisesRegex(DomainContractError, "status"):
            PhaseRecord.from_mapping({"phase_id": "p1", "status": "wat", "attempt": 0})

    def test_phase_attempt_preserves_projector_unknowns_when_requested(self) -> None:
        payload = {
            "run_id": "01J00000000000000000000000",
            "phase_id": "p1",
            "phase_title": "Phase",
            "attempt": 1,
            "status": "complete",
            "changed_files": ["src/app.py"],
            "failure_category": "launcher",
            "failure_known": True,
            "total_cost_usd": 0.42,
            "cost_confidence": "provider_reported",
            "permission_denial_count": 2,
            "future_projector_column": "kept",
        }

        with self.assertRaisesRegex(DomainContractError, "unknown"):
            PhaseAttemptRecord.from_mapping(payload)
        record = PhaseAttemptRecord.from_mapping(payload, preserve_unknown=True)
        self.assertEqual(record.to_dict(), payload)
        self.assertEqual(record.total_cost_usd, 0.42)
        self.assertEqual(dataclasses.replace(record, status="failed").to_dict()["status"], "failed")

    def test_phase_status_report_rejects_unknown_top_level_keys(self) -> None:
        payload = {
            "run_id": "01J00000000000000000000000",
            "status": "ready",
            "phases": [],
            "recommended_command": "bin/swarm do --prepared 01J00000000000000000000000 --phase-sessions auto",
        }

        self.assertEqual(PhaseStatusReport.from_mapping(payload).status, "ready")
        with self.assertRaisesRegex(DomainContractError, "unknown"):
            PhaseStatusReport.from_mapping({**payload, "surprise": True})

    def test_doctor_finding_round_trip_and_severity(self) -> None:
        payload = {
            "id": "lease_expired",
            "severity": "warning",
            "phase_id": "p1",
            "detail": "phase p1 lease expired",
            "recommended_command": "bin/swarm phases reap run",
        }

        self.assertEqual(DoctorFinding.from_mapping(payload).to_dict(), payload)
        self.assertEqual(DOCTOR_FINDING_SEVERITIES, frozenset({"error", "warning", "info"}))
        with self.assertRaisesRegex(DomainContractError, "severity"):
            DoctorFinding.from_mapping({**payload, "severity": "critical"})

    def test_missing_required_field_names_field(self) -> None:
        with self.assertRaisesRegex(DomainContractError, "phase_id"):
            PhaseRecord.from_mapping({"status": "pending", "attempt": 0})

    def test_domain_does_not_couple_to_persistence(self) -> None:
        domain_path = PIPELINE_ROOT / "domain.py"
        tree = ast.parse(domain_path.read_text(encoding="utf-8"), filename=str(domain_path))
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.endswith("SCHEMA_VERSION"):
                        violations.append(f"domain.py:{node.lineno}: imports {alias.name}")
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith("SCHEMA_VERSION"):
                        violations.append(f"domain.py:{node.lineno}: defines {target.id}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "schemas/" in node.value:
                violations.append(f"domain.py:{node.lineno}: references schemas/")
        for persister in ("phase_evidence.py", "prepared_artifact_writer.py", "mco_stage.py", "run_state.py"):
            persister_tree = ast.parse((PIPELINE_ROOT / persister).read_text(encoding="utf-8"), filename=persister)
            for node in ast.walk(persister_tree):
                if isinstance(node, ast.ImportFrom) and node.module in {"domain", ".domain", "swarm_do.pipeline.domain"}:
                    violations.append(f"{persister}:{node.lineno}: imports domain")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
