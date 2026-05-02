"""Property tests for role-spec path canonicalization."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, example, given, settings, strategies as st

from swarm_do.roles import cli as roles_cli

pytestmark = pytest.mark.unit

_SEGMENT = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=10,
).filter(lambda value: value not in {".", ".."})
_SEGMENTS = st.lists(_SEGMENT, min_size=0, max_size=4)
_PATH_VARIANTS = st.sampled_from(
    [
        "repo",
        "repo/",
        "repo/./sub/../sub",
        "/var/folders/xy/abc/repo",
        "/private/var/folders/xy/abc/repo",
    ]
)


def _make_repo(base: Path) -> Path:
    repo = base / "repo"
    (repo / "swarm-do" / "role-specs").mkdir(parents=True)
    return repo


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _variant_under_base(base: Path, raw: str) -> Path:
    if raw.startswith(("/var/", "/private/var/")):
        return base / "repo"
    return base / raw


@given(_SEGMENTS)
@example([])
@example(["sub"])
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_find_role_specs_dir_is_idempotent(segments: list[str]) -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = _make_repo(Path(td))
        cwd = _mkdir(repo.joinpath(*segments))
        with patch.object(Path, "cwd", return_value=cwd):
            first = roles_cli._find_role_specs_dir()
            second = roles_cli._find_role_specs_dir()
        assert first == second
        assert first == (repo / "swarm-do" / "role-specs").resolve()


@given(_PATH_VARIANTS)
@example("/var/folders/xy/abc/repo")
@example("/private/var/folders/xy/abc/repo")
@example("./repo")
@example("repo/")
@example("repo/./sub/../sub")
def test_role_specs_resolution_is_invariant_for_equivalent_paths(raw: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        repo = _make_repo(base)
        cwd = _mkdir(_variant_under_base(base, raw))
        with patch.object(Path, "cwd", return_value=cwd):
            from_variant = roles_cli._find_role_specs_dir()
        with patch.object(Path, "cwd", return_value=cwd.resolve(strict=False)):
            from_resolved = roles_cli._find_role_specs_dir()
        assert from_variant == from_resolved
        assert from_variant == (repo / "swarm-do" / "role-specs").resolve()


@given(_SEGMENTS, _SEGMENTS)
@example([], ["child"])
@example(["a"], ["b", "c"])
def test_role_specs_walk_is_monotonic_from_descendants(parent_segments: list[str], child_segments: list[str]) -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = _make_repo(Path(td))
        parent = _mkdir(repo.joinpath(*parent_segments))
        child = _mkdir(parent.joinpath(*child_segments))
        with patch.object(Path, "cwd", return_value=parent):
            parent_result = roles_cli._find_role_specs_dir()
        with patch.object(Path, "cwd", return_value=child):
            child_result = roles_cli._find_role_specs_dir()
        assert child_result == parent_result
        assert child_result == (repo / "swarm-do" / "role-specs").resolve()


@given(_SEGMENTS)
@example([])
@example(["unrelated", "nested"])
def test_file_walk_fallback_is_deterministic(segments: list[str]) -> None:
    with tempfile.TemporaryDirectory() as td:
        unrelated = _mkdir(Path(td).joinpath("outside", *segments))
        with patch.object(Path, "cwd", return_value=unrelated):
            first = roles_cli._find_role_specs_dir()
        with patch.object(Path, "cwd", return_value=unrelated / "missing" / ".."):
            second = roles_cli._find_role_specs_dir()
        assert first == second
        assert first.is_dir()
        assert first.name == "role-specs"
