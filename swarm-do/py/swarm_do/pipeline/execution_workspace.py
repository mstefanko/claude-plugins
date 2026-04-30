"""Safe cwd/path-spelling boundary for fresh launcher sessions."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


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

    def rewrite_prompt(self, text: str) -> tuple[str, int]:
        """Rewrite exact real repo-root spellings to the launcher-visible path."""

        if self.mode != "safe-symlink":
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

        if self.mode != "safe-symlink":
            return
        leaks = [spelling for spelling in self._sensitive_repo_spelling_variants() if spelling and spelling in text]
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
        return tuple(dict.fromkeys(pairs))


def create_execution_workspace(
    repo_root: Path,
    *,
    data_dir: Path,
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


__all__ = [
    "ExecutionWorkspace",
    "ExecutionWorkspaceError",
    "create_execution_workspace",
    "is_sensitive_path",
    "repo_id_for_path",
]
