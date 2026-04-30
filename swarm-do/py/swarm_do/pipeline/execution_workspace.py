"""Safe cwd/path-spelling boundary for fresh launcher sessions."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class ExecutionWorkspaceError(RuntimeError):
    """Raised when a safe launcher workspace cannot be constructed."""


@dataclass(frozen=True)
class ExecutionWorkspace:
    real_repo_root: Path
    launcher_repo_root: Path
    launcher_cwd: Path
    mode: str
    sensitive_prefixes: tuple[str, ...]
    safe_cwd_enabled: bool = True
    real_repo_spellings: tuple[str, ...] = ()
    prompt_rewrite_pairs: tuple[tuple[str, str], ...] = ()
    prompt_sensitive_spellings: tuple[str, ...] = ()
    worktree_metadata: Mapping[str, Any] | None = None

    def rewrite_prompt(self, text: str) -> tuple[str, int]:
        """Rewrite exact real repo-root spellings to the launcher-visible path."""

        if self.mode not in {"safe-symlink", "safe-worktree"} and not self.prompt_rewrite_pairs:
            return text, 0
        rewritten = text
        count = 0
        for spelling, replacement in self._rewrite_pairs():
            if not spelling or spelling == replacement:
                continue
            occurrences = rewritten.count(spelling)
            if occurrences:
                rewritten = rewritten.replace(spelling, replacement)
                count += occurrences
        return rewritten, count

    def assert_prompt_safe(self, text: str) -> None:
        """Fail before launch when the real sensitive repo root leaked."""

        if self.mode not in {"safe-symlink", "safe-worktree"} and not self.prompt_sensitive_spellings:
            return
        candidates = (*self._sensitive_repo_spelling_variants(), *self._prompt_sensitive_spelling_variants())
        leaks = [spelling for spelling in candidates if spelling and spelling in text]
        if leaks:
            sample = leaks[0]
            raise ExecutionWorkspaceError(f"launcher prompt still contains sensitive source path: {sample}")

    def to_metadata(self, *, prompt_rewrite_count: int | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "real_repo_root": str(self.real_repo_root),
            "launcher_repo_root": str(self.launcher_repo_root),
            "launcher_cwd": str(self.launcher_cwd),
            "execution_workspace_mode": self.mode,
            "safe_cwd_enabled": self.safe_cwd_enabled,
            "sensitive_prefixes": list(self.sensitive_prefixes),
        }
        if prompt_rewrite_count is not None:
            metadata["prompt_rewrite_count"] = int(prompt_rewrite_count)
        if self.worktree_metadata:
            metadata.update(dict(self.worktree_metadata))
        return metadata

    def _real_repo_spellings(self) -> tuple[str, ...]:
        values = list(self.real_repo_spellings) or [str(self.real_repo_root)]
        values.append(str(self.real_repo_root.resolve(strict=False)))
        return tuple(dict.fromkeys(values))

    def _sensitive_repo_spelling_variants(self) -> tuple[str, ...]:
        values: list[str] = []
        for spelling in self._real_repo_spellings():
            values.append(spelling)
            values.append(_json_slash_escape(spelling))
        return tuple(dict.fromkeys(value for value in values if value))

    def _rewrite_pairs(self) -> tuple[tuple[str, str], ...]:
        launcher = str(self.launcher_repo_root)
        pairs: list[tuple[str, str]] = []
        for spelling in self._real_repo_spellings():
            pairs.append((spelling, launcher))
            escaped_spelling = _json_slash_escape(spelling)
            if escaped_spelling != spelling:
                pairs.append((escaped_spelling, _json_slash_escape(launcher)))
        for spelling, replacement in self.prompt_rewrite_pairs:
            pairs.append((spelling, replacement))
            escaped_spelling = _json_slash_escape(spelling)
            escaped_replacement = _json_slash_escape(replacement)
            if escaped_spelling != spelling:
                pairs.append((escaped_spelling, escaped_replacement))
        return tuple(dict.fromkeys(pairs))

    def _prompt_sensitive_spelling_variants(self) -> tuple[str, ...]:
        values: list[str] = []
        for spelling in self.prompt_sensitive_spellings:
            values.append(spelling)
            values.append(_json_slash_escape(spelling))
        return tuple(dict.fromkeys(value for value in values if value))


def create_execution_workspace(
    repo_root: Path,
    *,
    data_dir: Path,
    run_id: str | None = None,
    prepared_plan: Mapping[str, Any] | None = None,
    enabled: bool | None = None,
    home: Path | None = None,
    sensitive_roots: Iterable[Path] | None = None,
) -> ExecutionWorkspace:
    """Return the cwd/path spelling Claude Code should see for a repo."""

    safe_enabled = _safe_cwd_enabled() if enabled is None else bool(enabled)
    raw_repo_root = Path(repo_root).expanduser()
    real_repo_root = raw_repo_root.resolve(strict=False)
    real_repo_spellings = tuple(dict.fromkeys([str(raw_repo_root), str(real_repo_root)]))
    prefixes = _sensitive_prefixes(home=home, sensitive_roots=sensitive_roots)
    if not safe_enabled:
        return ExecutionWorkspace(
            real_repo_root=real_repo_root,
            launcher_repo_root=real_repo_root,
            launcher_cwd=real_repo_root,
            mode="disabled",
            sensitive_prefixes=prefixes,
            safe_cwd_enabled=False,
            real_repo_spellings=real_repo_spellings,
        )
    if not is_sensitive_path(real_repo_root, sensitive_prefixes=prefixes):
        return ExecutionWorkspace(
            real_repo_root=real_repo_root,
            launcher_repo_root=real_repo_root,
            launcher_cwd=real_repo_root,
            mode="real",
            sensitive_prefixes=prefixes,
            real_repo_spellings=real_repo_spellings,
        )
    if run_id and prepared_plan is not None:
        try:
            from .execution_worktree import materialize_run_execution_worktree

            worktree = materialize_run_execution_worktree(
                run_id,
                source_project_root=real_repo_root,
                data_dir=Path(data_dir),
                prepared_plan=prepared_plan,
                sensitive_prefixes=prefixes,
            )
        except Exception as exc:
            raise ExecutionWorkspaceError(str(exc)) from exc
        rewrite_pairs = _worktree_rewrite_pairs(worktree)
        sensitive_spellings = (
            str(worktree.source_project_root),
            str(worktree.source_git_root),
            str(worktree.source_project_root.resolve(strict=False)),
            str(worktree.source_git_root.resolve(strict=False)),
        )
        return ExecutionWorkspace(
            real_repo_root=worktree.source_project_root,
            launcher_repo_root=worktree.safe_project_root,
            launcher_cwd=worktree.safe_project_root,
            mode="safe-worktree",
            sensitive_prefixes=prefixes,
            safe_cwd_enabled=True,
            real_repo_spellings=real_repo_spellings,
            prompt_rewrite_pairs=rewrite_pairs,
            prompt_sensitive_spellings=tuple(dict.fromkeys(sensitive_spellings)),
            worktree_metadata=worktree.to_metadata(),
        )
    launcher_repo_root = _ensure_launcher_symlink(real_repo_root, data_dir=Path(data_dir), sensitive_prefixes=prefixes)
    return ExecutionWorkspace(
        real_repo_root=real_repo_root,
        launcher_repo_root=launcher_repo_root,
        launcher_cwd=launcher_repo_root,
        mode="safe-symlink",
        sensitive_prefixes=prefixes,
        real_repo_spellings=real_repo_spellings,
    )


def is_sensitive_path(path: Path, *, sensitive_prefixes: Iterable[str] | None = None) -> bool:
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    for prefix_text in sensitive_prefixes or _sensitive_prefixes():
        prefix = Path(prefix_text).expanduser().resolve(strict=False)
        if _is_relative_to(candidate, prefix) or _is_relative_to(resolved, prefix):
            return True
    return False


def repo_id_for_path(repo_root: Path) -> str:
    text = str(Path(repo_root).expanduser().resolve(strict=False))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _safe_cwd_enabled() -> bool:
    value = os.environ.get("SWARM_CLAUDE_SAFE_CWD")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _sensitive_prefixes(
    *,
    home: Path | None = None,
    sensitive_roots: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    roots = list(sensitive_roots or ())
    if not roots:
        roots.append((home or Path.home()) / ".claude")
    return tuple(str(Path(root).expanduser().resolve(strict=False)) for root in roots)


def _ensure_launcher_symlink(real_repo_root: Path, *, data_dir: Path, sensitive_prefixes: tuple[str, ...]) -> Path:
    repo_id = repo_id_for_path(real_repo_root)
    launcher_dir = _safe_launcher_workspace_base(data_dir, sensitive_prefixes=sensitive_prefixes) / repo_id
    launcher_repo_root = launcher_dir / "repo"
    _assert_safe_launcher_parent(launcher_dir, sensitive_prefixes=sensitive_prefixes)
    launcher_dir.mkdir(parents=True, exist_ok=True)
    if launcher_repo_root.exists() or launcher_repo_root.is_symlink():
        _validate_launcher_symlink(launcher_repo_root, real_repo_root)
        return launcher_repo_root
    try:
        launcher_repo_root.symlink_to(real_repo_root, target_is_directory=True)
    except FileExistsError:
        _validate_launcher_symlink(launcher_repo_root, real_repo_root)
    _validate_launcher_symlink(launcher_repo_root, real_repo_root)
    return launcher_repo_root


def _assert_safe_launcher_parent(path: Path, *, sensitive_prefixes: tuple[str, ...]) -> None:
    resolved = path.expanduser().resolve(strict=False)
    if is_sensitive_path(resolved, sensitive_prefixes=sensitive_prefixes):
        raise ExecutionWorkspaceError(f"launcher workspace directory resolves inside a sensitive path: {path}")


def _validate_launcher_symlink(path: Path, real_repo_root: Path) -> None:
    if not path.is_symlink():
        raise ExecutionWorkspaceError(f"launcher workspace path exists but is not a symlink: {path}")
    target = Path(os.readlink(path))
    if not target.is_absolute():
        target = path.parent / target
    resolved_target = target.resolve(strict=False)
    if resolved_target != real_repo_root.resolve(strict=False):
        raise ExecutionWorkspaceError(
            f"launcher workspace symlink points at {resolved_target}, expected {real_repo_root.resolve(strict=False)}"
        )


def _is_relative_to(path: Path, prefix: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(prefix.resolve(strict=False))
        return True
    except ValueError:
        return False


def _safe_launcher_workspace_base(data_dir: Path, *, sensitive_prefixes: tuple[str, ...]) -> Path:
    candidates = [
        Path(data_dir).expanduser() / "launcher-workspaces",
        _default_data_dir() / "launcher-workspaces",
        Path("/tmp") / "swarmdaddy-launcher-workspaces",
        Path(tempfile.gettempdir()) / "swarmdaddy-launcher-workspaces",
    ]
    for candidate in _unique_paths(candidates):
        try:
            _assert_safe_launcher_parent(candidate, sensitive_prefixes=sensitive_prefixes)
        except ExecutionWorkspaceError:
            continue
        return candidate
    raise ExecutionWorkspaceError("no non-sensitive launcher workspace directory is available")


def _default_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg).expanduser() / "swarmdaddy"


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.expanduser().resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)


def _json_slash_escape(value: str) -> str:
    return value.replace("/", r"\/")


def _worktree_rewrite_pairs(worktree: Any) -> tuple[tuple[str, str], ...]:
    pairs = [
        (str(worktree.source_project_root), str(worktree.safe_project_root)),
        (str(worktree.source_project_root.resolve(strict=False)), str(worktree.safe_project_root.resolve(strict=False))),
        (str(worktree.source_git_root), str(worktree.safe_git_root)),
        (str(worktree.source_git_root.resolve(strict=False)), str(worktree.safe_git_root.resolve(strict=False))),
    ]
    for artifact in worktree.copied_artifacts:
        pairs.append((str(artifact.source_path), str(artifact.destination_path)))
        pairs.append((str(artifact.source_path.resolve(strict=False)), str(artifact.destination_path.resolve(strict=False))))
    return tuple(dict.fromkeys((source, destination) for source, destination in pairs if source and destination))


__all__ = [
    "ExecutionWorkspace",
    "ExecutionWorkspaceError",
    "create_execution_workspace",
    "is_sensitive_path",
    "repo_id_for_path",
]
