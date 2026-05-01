"""Run-start readiness gate shared by CLI dispatch paths."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from .beads_health import beads_where
from .paths import REPO_ROOT, resolve_data_dir
from .run_state import active_run_path, append_run_event, load_active_run, utc_now, validate_run_event


ProviderTier = Literal["path", "version", "handshake"]


@dataclasses.dataclass(frozen=True)
class PreflightFinding:
    id: str
    severity: str
    status: str
    summary: str
    details: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    remediation: str | None = None

    @property
    def blocking(self) -> bool:
        return self.severity == "hard" and self.status == "fail"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
            "remediation": self.remediation,
        }


@dataclasses.dataclass(frozen=True)
class PreflightReport:
    target_repo: str
    preset: str | None
    graph_source: str | None
    graph_source_name: str | None
    launchers: tuple[str, ...]
    provider_tier: ProviderTier
    findings: tuple[PreflightFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.blocker_ids

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        return tuple(finding.id for finding in self.findings if finding.blocking)

    @property
    def warning_ids(self) -> tuple[str, ...]:
        return tuple(
            finding.id
            for finding in self.findings
            if finding.status == "warn" or (finding.status == "fail" and finding.severity != "hard")
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "target_repo": self.target_repo,
            "preset": self.preset,
            "graph_source": self.graph_source,
            "graph_source_name": self.graph_source_name,
            "launchers": list(self.launchers),
            "provider_tier": self.provider_tier,
            "blocker_ids": list(self.blocker_ids),
            "warning_ids": list(self.warning_ids),
            "findings": [finding.as_dict() for finding in self.findings],
        }

    def raise_or_continue(self) -> None:
        if self.blocker_ids:
            raise RunPreflightError(self)


class RunPreflightError(RuntimeError):
    def __init__(self, report: PreflightReport):
        self.report = report
        super().__init__("run preflight failed: " + ", ".join(report.blocker_ids))


def run_preflight(
    *,
    run_id: str | None = None,
    target_repo: str | Path | None = None,
    data_dir: str | Path | None = None,
    preset: str | None = "current",
    graph_source: str | None = None,
    graph_source_name: str | None = None,
    launchers: Iterable[str] = ("manual", "fake-test", "claude-print"),
    require_provider_tier: ProviderTier = "version",
    git_base_sha: str | None = None,
) -> PreflightReport:
    """Return the run-start readiness report without writing telemetry."""

    base = Path(data_dir) if data_dir is not None else resolve_data_dir()
    repo = Path(target_repo) if target_repo is not None else REPO_ROOT
    launcher_tuple = tuple(dict.fromkeys(str(item) for item in launchers if str(item)))
    findings: list[PreflightFinding] = []

    if git_base_sha == "0" * 40:
        findings.append(
            PreflightFinding(
                "prepared-git-base-zero",
                "hard",
                "fail",
                "prepared run has an unavailable git base sha",
                {"git_base_sha": git_base_sha},
                "prepare from a git checkout with a resolvable HEAD, then accept the fresh prepared artifact",
            )
        )
    else:
        findings.append(
            PreflightFinding(
                "prepared-git-base-present",
                "hard",
                "pass",
                "prepared git base sha is present",
                {"git_base_sha": git_base_sha},
            )
        )

    beads = beads_where(repo)
    findings.append(
        PreflightFinding(
            "beads-rig-present",
            "hard",
            "pass" if beads.ok else "fail",
            beads.summary,
            beads.as_dict(),
            beads.remediation,
        )
    )

    findings.extend(_provider_findings(preset=preset, tier=require_provider_tier))
    findings.extend(_launcher_findings(launcher_tuple))
    findings.append(_active_run_finding(base, run_id))

    return PreflightReport(
        target_repo=str(repo.resolve(strict=False)),
        preset=preset,
        graph_source=graph_source,
        graph_source_name=graph_source_name,
        launchers=launcher_tuple,
        provider_tier=require_provider_tier,
        findings=tuple(findings),
    )


def record_run_preflight_completed(
    *,
    run_id: str,
    report: PreflightReport,
    data_dir: str | Path | None = None,
    bd_epic_id: str | None = None,
) -> Path:
    base = Path(data_dir) if data_dir is not None else resolve_data_dir()
    row: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": utc_now(),
        "event_type": "run_preflight_completed",
        "bd_epic_id": bd_epic_id,
        "phase_id": "prepared-dispatch",
        "work_unit_id": None,
        "child_bead_ids": None,
        "reason": None if report.ok else ", ".join(report.blocker_ids),
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": report.as_dict(),
        "schema_ok": True,
    }
    validate_run_event(row)
    return append_run_event(base, row)


def _provider_findings(*, preset: str | None, tier: ProviderTier) -> list[PreflightFinding]:
    from .providers import provider_doctor

    try:
        provider_preset = None if preset == "default" else preset
        doctor = provider_doctor(preset_name=provider_preset, backend_tier=tier)
    except Exception as exc:
        return [
            PreflightFinding(
                "provider-readiness",
                "hard",
                "fail",
                f"provider readiness probe failed: {exc}",
                {"preset": preset, "tier": tier},
            )
        ]
    findings: list[PreflightFinding] = []
    for check in doctor.checks:
        status = "pass" if check.status in {"ok", "skipped"} else ("warn" if check.status == "warning" else "fail")
        severity = "hard" if check.status == "error" else "advisory"
        findings.append(
            PreflightFinding(
                f"provider:{check.name}",
                severity,
                status,
                check.detail,
                check.as_dict(),
            )
        )
    return findings


def _launcher_findings(launchers: tuple[str, ...]) -> list[PreflightFinding]:
    from .session_capabilities import doctor_report

    report = doctor_report(live=False)
    by_name = {
        str(item.get("name")): item
        for item in report.get("launchers", [])
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    findings: list[PreflightFinding] = []
    for launcher in launchers:
        row = by_name.get(launcher)
        if row is None:
            findings.append(
                PreflightFinding(
                    f"launcher:{launcher}",
                    "hard",
                    "fail",
                    f"launcher {launcher} is not known",
                    {"launcher": launcher},
                )
            )
            continue
        eligible = bool(row.get("eligible"))
        findings.append(
            PreflightFinding(
                f"launcher:{launcher}",
                "hard",
                "pass" if eligible else "fail",
                f"launcher {launcher} is {'eligible' if eligible else 'ineligible'}",
                dict(row),
            )
        )
    return findings


def _active_run_finding(data_dir: Path, run_id: str | None) -> PreflightFinding:
    active = load_active_run(active_run_path(data_dir))
    if active is None:
        return PreflightFinding("active-run-clear", "hard", "pass", "no active run is present", {})
    active_run_id = active.get("run_id")
    status = active.get("status")
    details = {"active_run_id": active_run_id, "status": status, "active_run_path": str(active_run_path(data_dir))}
    if active_run_id == run_id:
        return PreflightFinding("active-run-same-run", "advisory", "pass", "active run already references this run", details)
    if status in {"complete", "completed", "merged", "cancelled", "failed", "blocked"}:
        return PreflightFinding("active-run-terminal", "advisory", "warn", "terminal active run should be cleared", details)
    return PreflightFinding(
        "active-run-conflict",
        "hard",
        "fail",
        "another non-terminal active run is present",
        details,
        "finish or clear the existing active run before dispatch",
    )


__all__ = [
    "PreflightFinding",
    "PreflightReport",
    "RunPreflightError",
    "record_run_preflight_completed",
    "run_preflight",
]
