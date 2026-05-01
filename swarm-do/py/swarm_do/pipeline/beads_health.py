"""Shared Beads readiness checks for run preflight and shell helpers."""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclasses.dataclass(frozen=True)
class BeadsWhereResult:
    ok: bool
    target_repo: str
    rig: str | None = None
    status: str = "fail"
    summary: str = "beads rig unavailable"
    remediation: str | None = "run /swarmdaddy:init-beads in the target repo before launching a swarm run"
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "target_repo": self.target_repo,
            "rig": self.rig,
            "summary": self.summary,
            "remediation": self.remediation,
            "details": dict(self.details),
        }


def beads_where(
    target_repo: str | Path,
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
    timeout_seconds: int = 10,
) -> BeadsWhereResult:
    """Run ``bd where`` in ``target_repo`` and normalize the result."""

    repo = Path(target_repo).resolve(strict=False)
    bd_path = which("bd")
    if bd_path is None:
        return BeadsWhereResult(
            ok=False,
            target_repo=str(repo),
            summary="bd CLI not found on PATH",
            details={"bd_path": None},
        )
    try:
        completed = runner(
            ["bd", "where"],
            cwd=str(repo),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return BeadsWhereResult(
            ok=False,
            target_repo=str(repo),
            summary=f"bd where timed out after {timeout_seconds}s",
            details={"bd_path": bd_path},
        )
    except OSError as exc:
        return BeadsWhereResult(
            ok=False,
            target_repo=str(repo),
            summary=f"bd where failed to start: {exc}",
            details={"bd_path": bd_path},
        )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0 or not stdout:
        return BeadsWhereResult(
            ok=False,
            target_repo=str(repo),
            summary="no Beads rig detected in target repo",
            details={
                "bd_path": bd_path,
                "exit_code": completed.returncode,
                "stderr": stderr,
            },
        )
    rig = stdout.splitlines()[0].strip()
    details: dict[str, Any] = {"bd_path": bd_path, "exit_code": completed.returncode}
    if stdout != rig:
        details["raw_stdout"] = stdout
    return BeadsWhereResult(
        ok=True,
        target_repo=str(repo),
        rig=rig,
        status="pass",
        summary="Beads rig detected",
        remediation=None,
        details=details,
    )


def beads_check_payload(result: BeadsWhereResult) -> dict[str, Any]:
    return result.as_dict()


__all__ = ["BeadsWhereResult", "beads_check_payload", "beads_where"]
