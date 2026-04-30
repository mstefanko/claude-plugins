"""Run-scoped execution worktrees for launcher hardening."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .run_state import _atomic_json_write, utc_now


class RunExecutionWorktreeError(RuntimeError):
    """Raised when a run execution worktree cannot be prepared or adopted."""


@dataclass(frozen=True)
class CopiedArtifact:
    source_path: Path
    destination_path: Path
    relative_path: str
    source_sha256: str
    destination_sha256: str
    kind: str
    transformed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "destination_path": str(self.destination_path),
            "relative_path": self.relative_path,
            "source_sha256": self.source_sha256,
            "destination_sha256": self.destination_sha256,
            "kind": self.kind,
            "transformed": self.transformed,
        }


@dataclass(frozen=True)
class RunExecutionWorktree:
    run_id: str
    source_git_root: Path
    source_project_root: Path
    safe_git_root: Path
    safe_project_root: Path
    project_subdir: str
    branch: str
    base_sha: str
    base_ref: str
    manifest_path: Path
    copied_artifacts: tuple[CopiedArtifact, ...]
    adoption_state: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source_git_top_level": str(self.source_git_root),
            "source_project_root": str(self.source_project_root),
            "safe_git_worktree_root": str(self.safe_git_root),
            "safe_project_root": str(self.safe_project_root),
            "project_subdir": self.project_subdir,
            "run_execution_branch": self.branch,
            "git_base_sha": self.base_sha,
            "git_base_ref": self.base_ref,
            "run_worktree_manifest_path": str(self.manifest_path),
            "copied_ignored_artifacts": [artifact.to_dict() for artifact in self.copied_artifacts],
            "adoption_state": self.adoption_state,
        }


@dataclass(frozen=True)
class ArtifactCopySpec:
    source_path: Path
    relative_path: Path
    kind: str
    required: bool = True
    transform: Callable[[bytes, "ResolvedExecutionWorktree"], bytes] | None = None


@dataclass(frozen=True)
class ResolvedExecutionWorktree:
    run_id: str
    source_git_root: Path
    source_project_root: Path
    safe_git_root: Path
    safe_project_root: Path
    project_subdir: str
    branch: str
    base_sha: str
    base_ref: str
    manifest_path: Path
    copy_specs: tuple[ArtifactCopySpec, ...]


def execution_branch_name(run_id: str) -> str:
    return f"swarm/{_safe_ref_segment(run_id)}/execution"


def resolve_run_execution_worktree(
    run_id: str,
    *,
    source_project_root: Path,
    data_dir: Path,
    prepared_plan: Mapping[str, Any],
    sensitive_prefixes: Iterable[str] = (),
) -> ResolvedExecutionWorktree:
    source_project = Path(source_project_root).expanduser().resolve(strict=False)
    source_git = Path(_git_stdout(source_project, "rev-parse", "--show-toplevel")).resolve(strict=False)
    prefix = _git_stdout(source_project, "rev-parse", "--show-prefix").strip()
    project_subdir = prefix.strip("/")
    expected_project = (source_git / project_subdir).resolve(strict=False) if project_subdir else source_git
    if expected_project != source_project:
        raise RunExecutionWorktreeError(
            f"git prefix maps to {expected_project}, expected source project root {source_project}"
        )
    _assert_supported_git_checkout(source_project)
    worktree_run_root = Path(data_dir).expanduser() / "worktrees" / run_id
    safe_git = (worktree_run_root / "repo").resolve(strict=False)
    safe_project = (safe_git / project_subdir).resolve(strict=False) if project_subdir else safe_git
    manifest_path = worktree_run_root / "manifest.json"
    _assert_not_sensitive(safe_git, sensitive_prefixes=sensitive_prefixes)
    _assert_not_sensitive(safe_project, sensitive_prefixes=sensitive_prefixes)
    _assert_not_sensitive(manifest_path, sensitive_prefixes=sensitive_prefixes)
    base_ref = str(prepared_plan.get("git_base_ref") or "HEAD")
    base_sha = _prepared_base_sha(source_project, prepared_plan, base_ref=base_ref)
    copy_specs = _artifact_copy_specs(
        run_id,
        data_dir=Path(data_dir),
        source_project_root=source_project,
        prepared_plan=prepared_plan,
    )
    return ResolvedExecutionWorktree(
        run_id=run_id,
        source_git_root=source_git,
        source_project_root=source_project,
        safe_git_root=safe_git,
        safe_project_root=safe_project,
        project_subdir=project_subdir,
        branch=execution_branch_name(run_id),
        base_sha=base_sha,
        base_ref=base_ref,
        manifest_path=manifest_path,
        copy_specs=copy_specs,
    )


def materialize_run_execution_worktree(
    run_id: str,
    *,
    source_project_root: Path,
    data_dir: Path,
    prepared_plan: Mapping[str, Any],
    sensitive_prefixes: Iterable[str] = (),
) -> RunExecutionWorktree:
    resolved = resolve_run_execution_worktree(
        run_id,
        source_project_root=source_project_root,
        data_dir=data_dir,
        prepared_plan=prepared_plan,
        sensitive_prefixes=sensitive_prefixes,
    )
    _assert_clean_source_project(resolved)
    existing_manifest = _load_manifest(resolved.manifest_path)
    if existing_manifest is not None:
        _validate_existing_manifest(resolved, existing_manifest)
        if not resolved.safe_git_root.exists():
            raise RunExecutionWorktreeError(f"run worktree manifest exists but checkout is missing: {resolved.safe_git_root}")
    else:
        _create_run_worktree(resolved)
    copied = _copy_required_artifacts(resolved)
    manifest = _manifest_payload(resolved, copied, previous=existing_manifest)
    _atomic_json_write(resolved.manifest_path, manifest)
    return RunExecutionWorktree(
        run_id=run_id,
        source_git_root=resolved.source_git_root,
        source_project_root=resolved.source_project_root,
        safe_git_root=resolved.safe_git_root,
        safe_project_root=resolved.safe_project_root,
        project_subdir=resolved.project_subdir,
        branch=resolved.branch,
        base_sha=resolved.base_sha,
        base_ref=resolved.base_ref,
        manifest_path=resolved.manifest_path,
        copied_artifacts=tuple(copied),
        adoption_state=str(manifest.get("adoption_state") or "unadopted"),
    )


def adopt_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    manifest_path = Path(data_dir) / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    safe_project = Path(str(manifest["safe_project_root"]))
    source_project = Path(str(manifest["source_project_root"]))
    copied_rels = {
        str(item.get("relative_path"))
        for item in manifest.get("copied_artifacts") or []
        if isinstance(item, Mapping) and isinstance(item.get("relative_path"), str)
    }
    changes = _status_changes(safe_project, project_subdir=str(manifest.get("project_subdir") or ""))
    operations: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for change in changes:
        rel = change["path"]
        block_reason = _adoption_block_reason(rel, copied_rels=copied_rels)
        if block_reason is not None:
            blocked.append({"path": rel, "reason": block_reason})
            continue
        safe_path = safe_project / rel
        destination = source_project / rel
        action = "delete" if change["status"].strip().startswith("D") or not safe_path.exists() else "copy"
        operations.append(
            {
                "action": action,
                "path": rel,
                "source_path": str(safe_path),
                "destination_path": str(destination),
            }
        )
    if apply and blocked:
        raise RunExecutionWorktreeError("adoption has blocked paths: " + ", ".join(item["path"] for item in blocked))
    applied_operations: list[dict[str, Any]] = []
    if apply:
        for operation in operations:
            src = Path(str(operation["source_path"]))
            dst = Path(str(operation["destination_path"]))
            if operation["action"] == "delete":
                if dst.is_dir():
                    shutil.rmtree(dst)
                elif dst.exists():
                    dst.unlink()
            else:
                if not src.is_file():
                    raise RunExecutionWorktreeError(f"cannot copy non-file changed path: {src}")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            applied_operations.append(operation)
        manifest = dict(manifest)
        manifest["adoption_state"] = "adopted"
        manifest["adopted_at"] = utc_now()
        manifest["last_used_at"] = utc_now()
        _atomic_json_write(manifest_path, manifest)
    return {
        "run_id": run_id,
        "applied": apply,
        "manifest_path": str(manifest_path),
        "source_project_root": str(source_project),
        "safe_project_root": str(safe_project),
        "run_execution_branch": manifest.get("branch"),
        "base_sha": manifest.get("base_sha"),
        "changed_files": [change["path"] for change in changes],
        "blocked_paths": blocked,
        "copyback_operations": operations,
        "applied_operations": applied_operations,
        "apply_command": f"bin/swarm worktrees adopt-run {run_id} --apply",
    }


def cleanup_run_worktree(run_id: str, *, data_dir: Path, apply: bool = False) -> dict[str, Any]:
    manifest_path = Path(data_dir) / "worktrees" / run_id / "manifest.json"
    manifest = _require_manifest(manifest_path)
    adoption_state = str(manifest.get("adoption_state") or "unadopted")
    safe_git = Path(str(manifest["safe_git_worktree_root"]))
    source_git = Path(str(manifest["source_git_root"]))
    eligible = adoption_state in {"adopted", "completed"}
    removed: list[str] = []
    if apply and not eligible:
        raise RunExecutionWorktreeError(
            f"run worktree is {adoption_state}; adopt or mark complete before cleanup"
        )
    if apply:
        result = _run_git(source_git, "worktree", "remove", "--force", str(safe_git), check=False)
        if result.returncode != 0 and safe_git.exists():
            shutil.rmtree(safe_git)
        removed.append(str(safe_git))
        manifest_path.unlink(missing_ok=True)
        try:
            manifest_path.parent.rmdir()
        except OSError:
            pass
    return {
        "run_id": run_id,
        "applied": apply,
        "eligible": eligible,
        "preserved_reason": None if eligible else f"worktree is {adoption_state}",
        "manifest_path": str(manifest_path),
        "safe_git_worktree_root": str(safe_git),
        "source_git_root": str(source_git),
        "targets": [str(safe_git), str(manifest_path)],
        "removed": removed,
        "apply_command": f"bin/swarm worktrees cleanup-run {run_id} --apply",
    }


def _assert_supported_git_checkout(source_project: Path) -> None:
    super_root = _git_stdout(source_project, "rev-parse", "--show-superproject-working-tree")
    if super_root.strip():
        raise RunExecutionWorktreeError("safe-worktree launcher does not support submodule project roots yet")
    sparse = _git_config_bool(source_project, "core.sparseCheckout")
    if sparse:
        raise RunExecutionWorktreeError("safe-worktree launcher does not support sparse-checkout sources yet")


def _assert_clean_source_project(resolved: ResolvedExecutionWorktree) -> None:
    scope = resolved.project_subdir or "."
    entries = _git_status_entries(
        resolved.source_git_root,
        scope,
    )
    allowed = {_git_relative_artifact_path(resolved, spec.relative_path) for spec in resolved.copy_specs}
    dirty: list[str] = []
    for entry in entries:
        paths = [entry.get("path"), entry.get("original_path")]
        present_paths = [path for path in paths if isinstance(path, str) and path]
        if present_paths and all(path in allowed for path in present_paths):
            continue
        dirty.append(_format_status_entry(entry))
    if dirty:
        raise RunExecutionWorktreeError(
            "source checkout has relevant dirty files under the project subdir; "
            "commit/stash them before safe-worktree launch: " + ", ".join(dirty)
        )


def _create_run_worktree(resolved: ResolvedExecutionWorktree) -> None:
    if resolved.safe_git_root.exists() and any(resolved.safe_git_root.iterdir()):
        raise RunExecutionWorktreeError(f"run worktree path already exists without a valid manifest: {resolved.safe_git_root}")
    if _branch_exists(resolved.source_git_root, resolved.branch):
        raise RunExecutionWorktreeError(f"run execution branch already exists without a valid manifest: {resolved.branch}")
    resolved.safe_git_root.parent.mkdir(parents=True, exist_ok=True)
    _git(resolved.source_git_root, "worktree", "add", "-b", resolved.branch, str(resolved.safe_git_root), resolved.base_sha)


def _copy_required_artifacts(resolved: ResolvedExecutionWorktree) -> list[CopiedArtifact]:
    copied: list[CopiedArtifact] = []
    for spec in _dedupe_copy_specs(resolved.copy_specs):
        if not spec.source_path.is_file():
            if spec.required:
                raise RunExecutionWorktreeError(f"required run artifact is missing: {spec.source_path}")
            continue
        destination = resolved.safe_project_root / spec.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_sha = _sha256_file(spec.source_path)
        transformed = False
        if spec.transform is not None:
            _atomic_write_bytes(destination, spec.transform(spec.source_path.read_bytes(), resolved))
            transformed = True
        else:
            _atomic_copy2(spec.source_path, destination)
        copied.append(
            CopiedArtifact(
                source_path=spec.source_path.resolve(strict=False),
                destination_path=destination.resolve(strict=False),
                relative_path=str(spec.relative_path),
                source_sha256=source_sha,
                destination_sha256=_sha256_file(destination),
                kind=spec.kind,
                transformed=transformed,
            )
        )
    return copied


def _manifest_payload(
    resolved: ResolvedExecutionWorktree,
    copied: list[CopiedArtifact],
    *,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    created_at = previous.get("created_at") if isinstance(previous, Mapping) and isinstance(previous.get("created_at"), str) else utc_now()
    adoption_state = (
        previous.get("adoption_state")
        if isinstance(previous, Mapping) and isinstance(previous.get("adoption_state"), str)
        else "unadopted"
    )
    return {
        "schema_version": 1,
        "run_id": resolved.run_id,
        "source_git_root": str(resolved.source_git_root),
        "source_project_root": str(resolved.source_project_root),
        "safe_git_worktree_root": str(resolved.safe_git_root),
        "safe_project_root": str(resolved.safe_project_root),
        "project_subdir": resolved.project_subdir,
        "branch": resolved.branch,
        "base_sha": resolved.base_sha,
        "base_ref": resolved.base_ref,
        "copied_artifacts": [artifact.to_dict() for artifact in copied],
        "adoption_state": adoption_state,
        "created_at": created_at,
        "last_used_at": utc_now(),
    }


def _validate_existing_manifest(resolved: ResolvedExecutionWorktree, manifest: Mapping[str, Any]) -> None:
    expected = {
        "run_id": resolved.run_id,
        "source_git_root": str(resolved.source_git_root),
        "source_project_root": str(resolved.source_project_root),
        "safe_git_worktree_root": str(resolved.safe_git_root),
        "safe_project_root": str(resolved.safe_project_root),
        "project_subdir": resolved.project_subdir,
        "branch": resolved.branch,
        "base_sha": resolved.base_sha,
    }
    mismatched = [key for key, expected_value in expected.items() if manifest.get(key) != expected_value]
    if mismatched:
        raise RunExecutionWorktreeError(
            "existing run worktree manifest does not match this run/base: " + ", ".join(mismatched)
        )


def _artifact_copy_specs(
    run_id: str,
    *,
    data_dir: Path,
    source_project_root: Path,
    prepared_plan: Mapping[str, Any],
) -> tuple[ArtifactCopySpec, ...]:
    run_rel = Path("data") / "runs" / run_id
    run_data = Path(data_dir) / "runs" / run_id
    specs: list[ArtifactCopySpec] = [
        ArtifactCopySpec(
            run_data / "prepared_plan.v1.json",
            run_rel / "prepared_plan.v1.json",
            "prepared_artifact",
            transform=_rebase_prepared_artifact,
        ),
        ArtifactCopySpec(source_project_root / str(prepared_plan.get("prepared_plan_path")), Path(str(prepared_plan.get("prepared_plan_path"))), "prepared_plan"),
    ]
    inspect = prepared_plan.get("inspect_artifact")
    if isinstance(inspect, Mapping) and isinstance(inspect.get("path"), str):
        specs.append(ArtifactCopySpec(source_project_root / str(inspect["path"]), Path(str(inspect["path"])), "inspect_artifact"))
    for descriptor in (prepared_plan.get("work_unit_artifacts") or {}).values():
        if isinstance(descriptor, Mapping) and isinstance(descriptor.get("path"), str):
            specs.append(
                ArtifactCopySpec(
                    source_project_root / str(descriptor["path"]),
                    Path(str(descriptor["path"])),
                    "work_unit_artifact",
                )
            )
    for relative, kind, transform in (
        (run_rel / "checkpoint.v1.json", "checkpoint", None),
        (run_rel / "phase_sessions.v1.json", "phase_sessions", None),
        (run_rel / "phase_recovery" / "worktree-baseline.json", "worktree_baseline", _rebase_baseline_artifact),
    ):
        source = run_data / relative.relative_to(run_rel)
        specs.append(ArtifactCopySpec(source, relative, kind, required=False, transform=transform))
    return tuple(specs)


def _rebase_prepared_artifact(raw: bytes, resolved: ResolvedExecutionWorktree) -> bytes:
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict):
        payload["repo_root"] = str(resolved.safe_project_root)
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _rebase_baseline_artifact(raw: bytes, resolved: ResolvedExecutionWorktree) -> bytes:
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict):
        payload["repo_root"] = str(resolved.safe_project_root)
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _prepared_base_sha(source_project: Path, prepared_plan: Mapping[str, Any], *, base_ref: str) -> str:
    value = prepared_plan.get("git_base_sha")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) and value != "0" * 40:
        return value
    return _git_stdout(source_project, "rev-parse", base_ref).strip()


def _status_changes(repo: Path, *, project_subdir: str = "") -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for entry in _git_status_entries(repo, "."):
        status = entry["status"]
        path = _project_relative_status_path(entry["path"], project_subdir=project_subdir)
        original = _project_relative_status_path(entry.get("original_path") or "", project_subdir=project_subdir)
        if _is_rename_status(status):
            if original:
                changes.append({"status": "D ", "path": original})
            if path:
                changes.append({"status": status, "path": path})
            continue
        if path:
            changes.append({"status": status, "path": path})
    return changes


def _git_status_entries(repo: Path, *pathspecs: str) -> list[dict[str, str]]:
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if pathspecs:
        args.extend(["--", *pathspecs])
    output = _run_git(repo, *args, check=True).stdout
    fields = output.split("\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        if len(field) < 4:
            continue
        status = field[:2]
        path = field[3:]
        entry = {"status": status, "path": path}
        if _is_rename_status(status) or _is_copy_status(status):
            if index < len(fields) and fields[index]:
                entry["original_path"] = fields[index]
                index += 1
        entries.append(entry)
    return entries


def _is_rename_status(status: str) -> bool:
    return "R" in status[:2]


def _is_copy_status(status: str) -> bool:
    return "C" in status[:2]


def _format_status_entry(entry: Mapping[str, str]) -> str:
    path = entry.get("path") or ""
    original = entry.get("original_path") or ""
    if original:
        return f"{original} -> {path}"
    return path


def _project_relative_status_path(path: str, *, project_subdir: str) -> str:
    prefix = project_subdir.strip("/")
    if prefix and path == prefix:
        return ""
    if prefix and path.startswith(prefix + "/"):
        return path[len(prefix) + 1 :]
    return path


def _adoption_block_reason(path: str, *, copied_rels: set[str]) -> str | None:
    rel = Path(path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        return "path_escape"
    if path in copied_rels or path.startswith("data/runs/"):
        return "run_artifact"
    return None


def _git_relative_artifact_path(resolved: ResolvedExecutionWorktree, rel: Path) -> str:
    return str((Path(resolved.project_subdir) / rel) if resolved.project_subdir else rel)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RunExecutionWorktreeError(f"run worktree manifest must be an object: {path}")
    return value


def _require_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_manifest(path)
    if manifest is None:
        raise RunExecutionWorktreeError(f"run worktree manifest not found: {path}")
    return manifest


def _dedupe_copy_specs(specs: Iterable[ArtifactCopySpec]) -> tuple[ArtifactCopySpec, ...]:
    result: list[ArtifactCopySpec] = []
    seen: set[str] = set()
    for spec in specs:
        key = str(spec.relative_path)
        if key in seen:
            continue
        seen.add(key)
        result.append(spec)
    return tuple(result)


def _assert_not_sensitive(path: Path, *, sensitive_prefixes: Iterable[str]) -> None:
    resolved = Path(path).expanduser().resolve(strict=False)
    for prefix_text in sensitive_prefixes:
        prefix = Path(prefix_text).expanduser().resolve(strict=False)
        try:
            resolved.relative_to(prefix)
        except ValueError:
            continue
        raise RunExecutionWorktreeError(f"safe worktree root resolves inside a sensitive path: {path}")


def _git_config_bool(repo: Path, key: str) -> bool:
    result = _run_git(repo, "config", "--bool", "--get", key, check=False)
    if result.returncode != 0:
        return False
    return result.stdout.strip().lower() == "true"


def _branch_exists(repo: Path, branch: str) -> bool:
    return _run_git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _git(repo: Path, *args: str) -> None:
    _run_git(repo, *args, check=True)


def _git_stdout(repo: Path, *args: str) -> str:
    return _run_git(repo, *args, check=True).stdout.strip()


def _git_lines(repo: Path, *args: str) -> list[str]:
    return [line for line in _git_stdout(repo, *args).splitlines() if line]


def _run_git(repo: Path, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise RunExecutionWorktreeError(_combined_output(result) or f"git {' '.join(args)} failed")
    return result


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def _safe_ref_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not safe or safe in {".", ".."}:
        raise ValueError(f"invalid git ref segment: {value!r}")
    return safe


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy2(source: Path, destination: Path) -> None:
    temp_path: Path | None = None
    try:
        with source.open("rb") as src, tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as tmp:
            temp_path = Path(tmp.name)
            shutil.copyfileobj(src, tmp, length=1024 * 1024)
        shutil.copystat(source, temp_path)
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _atomic_write_bytes(destination: Path, data: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(data)
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


__all__ = [
    "RunExecutionWorktree",
    "RunExecutionWorktreeError",
    "adopt_run_worktree",
    "cleanup_run_worktree",
    "execution_branch_name",
    "materialize_run_execution_worktree",
    "resolve_run_execution_worktree",
]
