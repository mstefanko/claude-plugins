"""normalize_path — Python port of bin/_lib/normalize-path.sh.

Parity reference: swarm-do/bin/_lib/normalize-path.sh (4-step pipeline):

  1. Resolve symlinks via `realpath -m` (resolves without requiring the path
     to exist).
  2. Strip WORKTREE_ROOT prefix if set and the resolved path is inside it.
  3. Strip the git REPO_ROOT prefix if `git rev-parse --show-toplevel` succeeds.
  4. Strip a leading `/` and emit verbatim if no prefix matched (fail-open).

Cross-run dedup depends on this normalization matching across codex_review
and claude_review extractors AND the legacy bash implementation. Do NOT
change semantics without coordinating with stable_finding_hash_v1.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


def _resolve(raw: str) -> str:
    """Step 1: resolve symlinks like the bash helper.

    Legacy shell behavior: attempts `realpath -m` first (GNU coreutils), then
    falls back to `readlink -f`. On macOS neither supports exist-agnostic mode,
    so the bash fallback becomes "use the raw path verbatim" when the path
    doesn't exist. We mirror that: only resolve when the path exists; leave
    non-existent paths untouched so WORKTREE_ROOT-based prefix strips continue
    to match user-supplied synthetic inputs.
    """
    try:
        if os.path.exists(raw):
            return str(Path(raw).resolve(strict=False))
    except OSError:
        pass
    return raw


def _strip_prefix(resolved: str, prefix: str) -> Optional[str]:
    """Return `resolved` with `prefix/` removed, or None if prefix doesn't match."""
    if not prefix:
        return None
    normalized_prefix = prefix.rstrip("/")
    if not normalized_prefix:
        return None
    sentinel = normalized_prefix + "/"
    if resolved.startswith(sentinel):
        return resolved[len(sentinel):].lstrip("/")
    return None


def _git_repo_root(resolved: str) -> Optional[str]:
    """Step 3 helper: ask git for the repo toplevel from the resolved path's dir."""
    probe_dir = resolved
    if os.path.isfile(probe_dir):
        probe_dir = os.path.dirname(probe_dir) or "."
    elif not os.path.isdir(probe_dir):
        # Non-existent path: walk up to first existing parent; fall back to CWD.
        probe = probe_dir
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                probe = ""
                break
            probe = parent
        probe_dir = probe or "."

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=probe_dir,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def normalize_path(raw: str, worktree_root: Optional[str] = None) -> str:
    """Canonicalize a file path for stable_finding_hash_v1 input.

    Fail-open: always returns a string; never raises. If no prefix matches,
    returns the resolved path with the leading `/` stripped (parity with
    `printf '%s\\n' "${_resolved#/}"` in normalize-path.sh:105).
    """
    if not raw:
        return raw

    resolved = _resolve(raw)

    wt = worktree_root if worktree_root is not None else os.environ.get("WORKTREE_ROOT", "")
    stripped = _strip_prefix(resolved, wt)
    if stripped is not None:
        return stripped

    repo_root = _git_repo_root(resolved)
    if repo_root:
        stripped = _strip_prefix(resolved, repo_root)
        if stripped is not None:
            return stripped

    return resolved.lstrip("/")
