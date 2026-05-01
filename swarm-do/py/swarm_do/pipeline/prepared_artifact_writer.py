"""Coordinated prepared-artifact mutations.

This module owns the coupled invariant between:

* the embedded work-unit artifact in prepared_plan.v1.json,
* the repo-visible work-unit sidecar bytes, and
* the descriptor sha stored in prepared_plan.v1.json.

Callers that need to mutate prepared dispatch state should go through this
module so the embedded copy, sidecar copy, and descriptor sha cannot drift.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .paths import resolve_data_dir
from .run_state import append_run_event, utc_now, validate_run_event


_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_REPLACE_DEPTH = 256


class RunStateTxn(Protocol):
    """Minimal transaction shape for future state-store backends."""

    def __enter__(self) -> "RunStateTxn": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None: ...


class RunStateStore(Protocol):
    """Storage seam for run-state mutation backends."""

    def load(self, run_id: str) -> dict[str, Any]: ...

    def begin(self) -> AbstractContextManager[RunStateTxn]: ...


@dataclass(frozen=True)
class RefreshBaseResult:
    run_id: str
    target_git_base_sha: str
    previous_git_base_sha: str
    phase_ids: tuple[str, ...]
    changed: bool
    dry_run: bool
    artifact_path: str
    backups: tuple[str, ...]
    touched_paths: tuple[str, ...]
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_git_base_sha": self.target_git_base_sha,
            "previous_git_base_sha": self.previous_git_base_sha,
            "phase_ids": list(self.phase_ids),
            "changed": self.changed,
            "dry_run": self.dry_run,
            "artifact_path": self.artifact_path,
            "backups": list(self.backups),
            "touched_paths": list(self.touched_paths),
            "events": list(self.events),
        }


class JsonRunStateStore:
    """JSON-file run-state backend used by the current implementation."""

    def __init__(self, *, data_dir: Path | None = None, repo_root: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else resolve_data_dir()
        self.repo_root = Path(repo_root) if repo_root is not None else None

    def load(self, run_id: str) -> dict[str, Any]:
        from .prepare import load_prepared_artifact

        return load_prepared_artifact(run_id, data_dir=self.data_dir, repo_root=self.repo_root)

    def begin(self) -> AbstractContextManager[RunStateTxn]:
        return _NullRunStateTxn()


class _NullRunStateTxn:
    def __enter__(self) -> "_NullRunStateTxn":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class PreparedArtifactWriter:
    """Atomic prepared dispatch artifact mutator."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        repo_root: Path | None = None,
        store: RunStateStore | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else resolve_data_dir()
        self.repo_root = Path(repo_root) if repo_root is not None else None
        self.store = store or JsonRunStateStore(data_dir=self.data_dir, repo_root=self.repo_root)

    def load(self, run_id: str) -> dict[str, Any]:
        return self.store.load(run_id)

    def refresh_base(
        self,
        run_id: str,
        *,
        to_sha: str | None = None,
        to_head: bool = False,
        phase_id: str | None = None,
        dry_run: bool = False,
        operator_id: str | None = None,
        reason: str = "to-head",
        fail_at: str | None = None,
    ) -> RefreshBaseResult:
        """Refresh prepared dispatch state to a new git base sha.

        The whole run is committed as one hand-rolled write-ahead transaction:
        snapshot every touched file, stage every new body, replace the files,
        verify with the dispatch validators, and restore on failure.
        """

        from .prepare import (
            _artifact_path,
            _resolve_repo_root,
            canonicalize,
            verify_prepared_payload,
        )

        payload = self.load(run_id)
        root = _resolve_repo_root(payload, repo_root=self.repo_root).resolve(strict=False)
        previous_sha = str(payload["git_base_sha"])
        if phase_id is not None and to_sha is None and not to_head:
            target_sha = previous_sha
        else:
            target_sha = _resolve_target_sha(root, payload, to_sha=to_sha)
        if not _GIT_SHA_RE.match(target_sha):
            raise ValueError(f"target git sha must be a 40-char hex digest: {target_sha}")
        if phase_id is not None and target_sha != previous_sha:
            raise ValueError(
                "phase-scoped refresh-base cannot change top-level git_base_sha; "
                "use whole-run `swarm prepare refresh-base <run-id>` to move the base"
            )

        updated = copy.deepcopy(payload)
        selected = _selected_phase_ids(updated, phase_id=phase_id)
        if phase_id is None:
            updated["git_base_sha"] = target_sha

        staged: dict[Path, bytes] = {}
        events: list[dict[str, Any]] = []
        touched_paths: list[Path] = []
        phase_ids: list[str] = []

        descriptors = updated.get("work_unit_artifacts")
        if not isinstance(descriptors, dict):
            raise ValueError("prepared artifact work_unit_artifacts must be an object")

        for current_phase_id in selected:
            descriptor = descriptors.get(current_phase_id)
            if not isinstance(descriptor, dict):
                raise ValueError(f"work_unit_artifacts[{current_phase_id}] is invalid")
            artifact = descriptor.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError(f"work_unit_artifacts[{current_phase_id}].artifact is missing")
            before_sidecar_sha = str(descriptor.get("sha") or "")
            before_phase_sha = artifact.get("git_base_sha")
            artifact["git_base_sha"] = target_sha
            sidecar_rel = canonicalize(str(descriptor["path"]), repo_root=root)
            sidecar_path = (root / sidecar_rel).resolve(strict=False)
            sidecar_bytes = canonical_json_bytes(artifact)
            descriptor["sha"] = sha256_bytes(sidecar_bytes)
            staged[sidecar_path] = sidecar_bytes
            touched_paths.append(sidecar_path)
            phase_ids.append(current_phase_id)
            events.append(
                {
                    "phase_id": current_phase_id,
                    "before_git_base_sha": before_phase_sha,
                    "after_git_base_sha": target_sha,
                    "before_sidecar_sha": before_sidecar_sha,
                    "after_sidecar_sha": descriptor["sha"],
                    "sidecar_path": str(sidecar_path),
                }
            )

        inspect_descriptor = updated.get("inspect_artifact")
        if phase_id is None and isinstance(inspect_descriptor, dict) and isinstance(inspect_descriptor.get("path"), str):
            inspect_path = (root / canonicalize(inspect_descriptor["path"], repo_root=root)).resolve(strict=False)
            if inspect_path.is_file():
                inspect_payload = json.loads(inspect_path.read_text(encoding="utf-8"))
                if isinstance(inspect_payload, dict) and _replace_key_recursive(
                    inspect_payload,
                    key="git_base_sha",
                    value=target_sha,
                ):
                    inspect_bytes = canonical_json_bytes(inspect_payload)
                    inspect_descriptor["sha"] = sha256_bytes(inspect_bytes)
                    staged[inspect_path] = inspect_bytes
                    touched_paths.append(inspect_path)

        artifact_path = _artifact_path(run_id=run_id, data_dir=self.data_dir)
        staged[artifact_path] = canonical_json_bytes(updated)
        touched_paths.append(artifact_path)

        changed = any((not path.is_file()) or path.read_bytes() != body for path, body in staged.items())
        if dry_run:
            return RefreshBaseResult(
                run_id=run_id,
                target_git_base_sha=target_sha,
                previous_git_base_sha=previous_sha,
                phase_ids=tuple(phase_ids),
                changed=changed,
                dry_run=True,
                artifact_path=str(artifact_path),
                backups=(),
                touched_paths=tuple(str(path) for path in _dedupe_paths(touched_paths)),
                events=tuple(events),
            )

        if not changed:
            verify_prepared_payload(updated, artifact_path=artifact_path, repo_root=root)
            return RefreshBaseResult(
                run_id=run_id,
                target_git_base_sha=target_sha,
                previous_git_base_sha=previous_sha,
                phase_ids=tuple(phase_ids),
                changed=False,
                dry_run=False,
                artifact_path=str(artifact_path),
                backups=(),
                touched_paths=tuple(str(path) for path in _dedupe_paths(touched_paths)),
                events=(),
            )

        backups = self._commit_staged(
            staged,
            updated_payload=updated,
            repo_root=root,
            fail_at=fail_at,
        )
        event_rows = self._append_refresh_events(
            run_id,
            events=events,
            operator_id=operator_id,
            reason=reason,
            target_sha=target_sha,
        )
        return RefreshBaseResult(
            run_id=run_id,
            target_git_base_sha=target_sha,
            previous_git_base_sha=previous_sha,
            phase_ids=tuple(phase_ids),
            changed=True,
            dry_run=False,
            artifact_path=str(artifact_path),
            backups=tuple(str(path) for path in backups),
            touched_paths=tuple(str(path) for path in _dedupe_paths(touched_paths)),
            events=tuple(event_rows),
        )

    def _commit_staged(
        self,
        staged: Mapping[Path, bytes],
        *,
        updated_payload: Mapping[str, Any],
        repo_root: Path,
        fail_at: str | None,
    ) -> list[Path]:
        from .prepare import verify_prepared_payload

        stamp = _operation_stamp()
        normalized_staged = {Path(path).resolve(strict=False): body for path, body in staged.items()}
        backups: dict[Path, Path] = {}
        tmp_paths: dict[Path, Path] = {}
        committed: list[Path] = []
        paths = _dedupe_paths(normalized_staged.keys())
        try:
            if fail_at == "snapshot":
                raise OSError("injected refresh-base snapshot failure")
            for path in paths:
                if not path.is_file():
                    raise FileNotFoundError(f"refresh-base target missing: {path}")
                backup = path.with_name(f"{path.name}.bak-before-refresh-base-{stamp}")
                shutil.copy2(path, backup)
                backups[path] = backup

            if fail_at == "stage":
                raise OSError("injected refresh-base stage failure")
            for path in paths:
                tmp = path.with_name(f".{path.name}.tmp-refresh-base-{stamp}")
                tmp.write_bytes(normalized_staged[path])
                tmp_paths[path] = tmp

            for index, path in enumerate(paths, start=1):
                os.replace(tmp_paths[path], path)
                committed.append(path)
                if fail_at in {"commit", f"commit:{index}"}:
                    raise OSError("injected refresh-base commit failure")

            if fail_at == "verify":
                raise ValueError("injected refresh-base verify failure")
            verify_prepared_payload(updated_payload, repo_root=repo_root)
            return [backups[path] for path in paths]
        except Exception:
            for path in reversed(committed):
                backup = backups.get(path)
                if backup is not None and backup.exists():
                    os.replace(backup, path)
            raise
        finally:
            for tmp in tmp_paths.values():
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass

    def _append_refresh_events(
        self,
        run_id: str,
        *,
        events: list[dict[str, Any]],
        operator_id: str | None,
        reason: str,
        target_sha: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        actor = operator_id or os.environ.get("USER") or "unknown"
        for event in events:
            row = {
                "run_id": run_id,
                "timestamp": utc_now(),
                "event_type": "prepared_dispatch_refreshed",
                "bd_epic_id": None,
                "phase_id": event["phase_id"],
                "work_unit_id": None,
                "child_bead_ids": None,
                "reason": reason,
                "retry_count": None,
                "handoff_count": None,
                "integration_branch_head": None,
                "details": {
                    **event,
                    "operator_id": actor,
                    "target_git_base_sha": target_sha,
                },
                "schema_ok": True,
            }
            validate_run_event(row)
            append_run_event(self.data_dir, row)
            rows.append(row)
        return rows


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def prepared_plan_git_base_fields(*, git_base_ref: str, git_base_sha: str) -> dict[str, str]:
    _validate_git_base_ref(git_base_ref)
    _validate_git_base_sha(git_base_sha)
    return {
        "git_base_ref": git_base_ref,
        "git_base_sha": git_base_sha,
    }


def stamp_work_unit_git_base(
    artifact: dict[str, Any],
    *,
    git_base_ref: str,
    git_base_sha: str,
) -> None:
    artifact.update(prepared_plan_git_base_fields(git_base_ref=git_base_ref, git_base_sha=git_base_sha))


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def resolve_git_commit(repo_root: Path, ref: str) -> str:
    _validate_git_base_ref(ref)
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"cannot resolve git base ref {ref!r}: {detail}")
    sha = result.stdout.strip()
    _validate_git_base_sha(sha)
    return sha


def _resolve_target_sha(
    repo_root: Path,
    payload: Mapping[str, Any],
    *,
    to_sha: str | None,
) -> str:
    if to_sha:
        return to_sha.strip()
    ref = str(payload.get("git_base_ref") or "HEAD")
    return resolve_git_commit(repo_root, ref)


def _selected_phase_ids(payload: Mapping[str, Any], *, phase_id: str | None) -> tuple[str, ...]:
    descriptors = payload.get("work_unit_artifacts")
    if not isinstance(descriptors, Mapping):
        raise ValueError("prepared artifact work_unit_artifacts must be an object")
    if phase_id is not None:
        if phase_id not in descriptors:
            raise ValueError(f"phase not found in work_unit_artifacts: {phase_id}")
        return (phase_id,)
    return tuple(str(item.get("phase_id")) for item in payload.get("phase_map") or [] if isinstance(item, Mapping))


def _replace_key_recursive(
    node: object,
    *,
    key: str,
    value: str,
    max_depth: int = _MAX_REPLACE_DEPTH,
) -> int:
    if max_depth < 0:
        raise ValueError(f"maximum JSON depth exceeded while replacing {key!r}")
    count = 0
    if isinstance(node, dict):
        for current_key, current_value in list(node.items()):
            if current_key == key and isinstance(current_value, str):
                if current_value != value:
                    node[current_key] = value
                    count += 1
            else:
                count += _replace_key_recursive(
                    current_value,
                    key=key,
                    value=value,
                    max_depth=max_depth - 1,
                )
    elif isinstance(node, list):
        for item in node:
            count += _replace_key_recursive(
                item,
                key=key,
                value=value,
                max_depth=max_depth - 1,
            )
    return count


def _dedupe_paths(paths: Any) -> list[Path]:
    result: list[Path] = []
    seen: set[tuple[Any, ...]] = set()
    for path in paths:
        resolved = Path(path).resolve(strict=False)
        key = _path_identity_key(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _path_identity_key(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
    except OSError:
        return ("path", os.path.normcase(str(path)))
    return ("inode", stat.st_dev, stat.st_ino)


def _validate_git_base_ref(ref: str) -> None:
    if not ref or ref.startswith("-"):
        raise ValueError(f"git base ref must not be empty or option-like: {ref!r}")


def _validate_git_base_sha(sha: str) -> None:
    if not _GIT_SHA_RE.match(sha):
        raise ValueError(f"git base sha must be a 40-char hex digest: {sha}")


def _operation_stamp() -> str:
    return utc_now().replace(":", "").replace(".", "-")


__all__ = [
    "JsonRunStateStore",
    "PreparedArtifactWriter",
    "RefreshBaseResult",
    "RunStateStore",
    "RunStateTxn",
    "canonical_json_bytes",
    "prepared_plan_git_base_fields",
    "resolve_git_commit",
    "sha256_bytes",
    "stamp_work_unit_git_base",
]
