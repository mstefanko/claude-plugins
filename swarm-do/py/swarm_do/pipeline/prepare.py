# prepare.py

"""Prepared run artifact contract for /swarmdaddy:prepare.

This module owns the prepared_plan.v1.json contract that connects the prepare
gate (review -> normalize -> decompose -> acceptance) to execution. It defines:

* :func:`canonicalize` -- the trust-boundary helper for repo-relative paths.
* hashing primitives (``_sha256_bytes``, ``_sha256_file``).
* :func:`_compute_cache_key` -- per-phase cache-key composition.
* :func:`_validate_against_schema` -- stdlib-only payload linter against
  ``swarm-do/schemas/prepared_plan.schema.json`` (no jsonschema dep).
* persistence helpers: :func:`write_prepared_artifact`,
  :func:`load_prepared_artifact`.
* state-transition helpers: :func:`mark_ready_for_acceptance`,
  :func:`accept_prepared`, :func:`reject_prepared`, plus
  :class:`InvalidPreparedTransition`.
* drift detection: :class:`StaleReason` + :func:`check_stale`.

Beads-optionality: this module MUST NOT import ``bd``. Tests run with no rig.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT, resolve_data_dir
from .run_state import utc_now

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
PREPARE_POLICY_VERSION = 1
WORK_UNITS_SCHEMA_VERSION = 2
# [UNVERIFIED] Phase 3 owns the agent role spec; default placeholder for now.
_AGENT_DECOMPOSE_ROLE_VERSION = "v1"

STATUS_DRAFT = "draft"
STATUS_READY = "ready_for_acceptance"
STATUS_NEEDS_INPUT = "needs_input"
STATUS_ACCEPTED = "accepted"
STATUS_STALE = "stale"
STATUS_REJECTED = "rejected"

_VALID_STATUSES = frozenset(
    {
        STATUS_DRAFT,
        STATUS_READY,
        STATUS_NEEDS_INPUT,
        STATUS_ACCEPTED,
        STATUS_STALE,
        STATUS_REJECTED,
    }
)
_VALID_COMPLEXITIES = frozenset({"simple", "moderate", "hard"})

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_SCHEMA_PATH = REPO_ROOT / "schemas" / "prepared_plan.schema.json"
_ARTIFACT_NAME = "prepared_plan.v1.json"

# Path fields that must round-trip through canonicalize() at load time.
# (``repo_root`` is itself the trust root and is exempted.)
_PATH_FIELDS = ("source_plan_path", "prepared_plan_path")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidPreparedTransition(ValueError):
    """Raised when accept_prepared is called from a non-ready status.

    Subclasses :class:`ValueError` so that callers using broad ``except
    ValueError`` continue to handle the failure as fail-closed without
    needing module-specific imports.
    """


# ---------------------------------------------------------------------------
# Trust boundary
# ---------------------------------------------------------------------------


def canonicalize(path: str | os.PathLike[str], *, repo_root: Path) -> Path:
    """Resolve ``path`` against ``repo_root`` and return a repo-relative Path.

    Per Phase 1 coordinator decision Q1: ``Path.resolve(strict=False)`` is
    used so missing leaves still validate; resolved paths that escape
    ``repo_root`` are rejected. Absolute inputs and ``..`` segments are
    rejected before resolution. Empty strings are rejected.

    Known limitations recorded in ADR 0006 §Consequences:

    * Case-insensitive filesystems (default on macOS / Windows) cannot
      distinguish ``Plan.md`` from ``plan.md``.
    * Windows drive letters / UNC paths are out of scope for v1.
    """

    if isinstance(path, (str, bytes)):
        text = path.decode() if isinstance(path, bytes) else path
        if text == "" or text.strip() == "":
            raise ValueError("empty path forbidden")
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError(f"absolute path forbidden: {path}")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"path with .. segment forbidden: {path}")
    root = Path(repo_root).resolve(strict=False)
    resolved = (root / candidate).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"out-of-repo path forbidden: {path}")
    return resolved.relative_to(root)


# ---------------------------------------------------------------------------
# Hashing primitives
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_cache_key(
    *,
    content_sha: str,
    prepared_plan_sha: str,
    plan_context_sha: str,
) -> str:
    """Compose the per-phase cache key.

    Inputs (sorted, newline-separated, fed into a single sha256):

    1. ``content_sha`` -- per-phase content hash from phase_map.
    2. ``prepared_plan_sha`` -- whole-plan sha snapshot at prepare time.
    3. ``plan_context_sha`` -- normalized plan-context hash.
    4. ``SCHEMA_VERSION`` -- the prepared-plan schema version.
    5. ``WORK_UNITS_SCHEMA_VERSION`` -- decomposed sidecar schema version.
    6. ``_AGENT_DECOMPOSE_ROLE_VERSION`` -- decompose role spec version.
    7. ``PREPARE_POLICY_VERSION`` -- prepare-gate policy version.

    Source: design plan lines 91-96.
    """

    inputs = [
        content_sha,
        prepared_plan_sha,
        plan_context_sha,
        str(SCHEMA_VERSION),
        str(WORK_UNITS_SCHEMA_VERSION),
        _AGENT_DECOMPOSE_ROLE_VERSION,
        str(PREPARE_POLICY_VERSION),
    ]
    payload = "\n".join(inputs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Atomic write (mirror of run_state._atomic_json_write at run_state.py:144)
# ---------------------------------------------------------------------------


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    """Write ``payload`` to ``path`` atomically.

    Mirrors the run_state.py:144 idiom (NamedTemporaryFile in same parent ->
    fsync -> os.replace). Kept local here so the prepare module is
    independently auditable.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        tmp.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# Schema validator (stdlib-only)
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, Any] | None = None


def _load_schema() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_against_schema(payload: Mapping[str, Any]) -> None:
    """Minimal stdlib validator for the prepared_plan.v1 contract.

    Intentionally NOT a generic JSON-schema engine; only the shapes the
    schema declares are enforced. Raises ``ValueError`` on first failure.
    """

    schema = _load_schema()

    if not isinstance(payload, Mapping):
        raise ValueError("prepared_plan payload must be a mapping")

    # Required top-level keys.
    for key in schema["required"]:
        _require(key in payload, f"prepared_plan: missing required key: {key}")

    # additionalProperties=false at the top level.
    allowed_top = set(schema["properties"].keys())
    for key in payload.keys():
        _require(
            key in allowed_top,
            f"prepared_plan: unknown key: {key}",
        )

    # schema_version
    _require(
        isinstance(payload["schema_version"], int)
        and payload["schema_version"] in schema["properties"]["schema_version"]["enum"],
        f"prepared_plan: schema_version must be in {schema['properties']['schema_version']['enum']}",
    )

    # run_id (ULID)
    _require(
        isinstance(payload["run_id"], str) and bool(_ULID_RE.match(payload["run_id"])),
        "prepared_plan: run_id must match ULID pattern",
    )

    # status enum
    _require(
        isinstance(payload["status"], str) and payload["status"] in _VALID_STATUSES,
        f"prepared_plan: status must be one of {sorted(_VALID_STATUSES)}",
    )

    # sha fields
    for sha_key in (
        "source_plan_sha",
        "prepared_plan_sha",
    ):
        value = payload[sha_key]
        _require(
            isinstance(value, str) and bool(_SHA256_RE.match(value)),
            f"prepared_plan: {sha_key} must be a sha256 hex digest",
        )
    _require(
        isinstance(payload["git_base_sha"], str)
        and bool(_GIT_SHA_RE.match(payload["git_base_sha"])),
        "prepared_plan: git_base_sha must be a 40-char hex digest",
    )

    # repo_root / git_base_ref / source_plan_path / prepared_plan_path
    for str_key in (
        "repo_root",
        "git_base_ref",
        "source_plan_path",
        "prepared_plan_path",
        "created_at",
    ):
        value = payload[str_key]
        _require(
            isinstance(value, str) and len(value) > 0,
            f"prepared_plan: {str_key} must be a non-empty string",
        )

    for nullable_str_key in ("ready_at", "accepted_at"):
        value = payload[nullable_str_key]
        _require(
            value is None or (isinstance(value, str) and len(value) > 0),
            f"prepared_plan: {nullable_str_key} must be null or non-empty string",
        )

    # inspect_artifact
    inspect = payload["inspect_artifact"]
    _require(isinstance(inspect, Mapping), "prepared_plan: inspect_artifact must be object")
    _require(
        set(inspect.keys()) == {"path", "sha"},
        "prepared_plan: inspect_artifact keys must be exactly {path, sha}",
    )
    _require(
        isinstance(inspect["path"], str) and len(inspect["path"]) > 0,
        "prepared_plan: inspect_artifact.path must be non-empty string",
    )
    _require(
        isinstance(inspect["sha"], str) and bool(_SHA256_RE.match(inspect["sha"])),
        "prepared_plan: inspect_artifact.sha must be sha256",
    )

    # phase_map
    phase_map = payload["phase_map"]
    _require(isinstance(phase_map, list), "prepared_plan: phase_map must be a list")
    seen_phase_ids: set[str] = set()
    for idx, item in enumerate(phase_map):
        _require(isinstance(item, Mapping), f"prepared_plan: phase_map[{idx}] must be object")
        required_phase_keys = {
            "phase_id",
            "title",
            "complexity",
            "kind",
            "content_sha",
            "plan_context_sha",
            "cache_key",
            "requires_decomposition",
        }
        _require(
            set(item.keys()) == required_phase_keys,
            f"prepared_plan: phase_map[{idx}] keys must be exactly {sorted(required_phase_keys)}",
        )
        _require(
            isinstance(item["phase_id"], str) and len(item["phase_id"]) > 0,
            f"prepared_plan: phase_map[{idx}].phase_id must be non-empty string",
        )
        _require(
            item["phase_id"] not in seen_phase_ids,
            f"prepared_plan: phase_map[{idx}].phase_id duplicate: {item['phase_id']}",
        )
        seen_phase_ids.add(item["phase_id"])
        _require(
            isinstance(item["title"], str),
            f"prepared_plan: phase_map[{idx}].title must be string",
        )
        _require(
            item["complexity"] in _VALID_COMPLEXITIES,
            f"prepared_plan: phase_map[{idx}].complexity invalid",
        )
        _require(
            item["kind"] is None or isinstance(item["kind"], str),
            f"prepared_plan: phase_map[{idx}].kind must be string or null",
        )
        for sha_field in ("content_sha", "plan_context_sha", "cache_key"):
            _require(
                isinstance(item[sha_field], str)
                and bool(_SHA256_RE.match(item[sha_field])),
                f"prepared_plan: phase_map[{idx}].{sha_field} must be sha256",
            )
        _require(
            isinstance(item["requires_decomposition"], bool),
            f"prepared_plan: phase_map[{idx}].requires_decomposition must be bool",
        )

    # review_findings & accepted_fixes
    for list_key in ("review_findings", "accepted_fixes"):
        value = payload[list_key]
        _require(isinstance(value, list), f"prepared_plan: {list_key} must be list")
        for j, entry in enumerate(value):
            _require(
                isinstance(entry, Mapping),
                f"prepared_plan: {list_key}[{j}] must be object",
            )

    # review_iteration_count
    rc = payload["review_iteration_count"]
    _require(
        isinstance(rc, int) and not isinstance(rc, bool),
        "prepared_plan: review_iteration_count must be integer",
    )
    _require(
        0 <= rc <= 3,
        f"prepared_plan: review_iteration_count must be in [0, 3], got {rc}",
    )

    # work_unit_artifacts: keys MUST be phase_ids in phase_map.
    wua = payload["work_unit_artifacts"]
    _require(isinstance(wua, Mapping), "prepared_plan: work_unit_artifacts must be object")
    for phase_id, descriptor in wua.items():
        _require(
            phase_id in seen_phase_ids,
            f"prepared_plan: work_unit_artifacts key {phase_id!r} not in phase_map",
        )
        _require(
            isinstance(descriptor, Mapping),
            f"prepared_plan: work_unit_artifacts[{phase_id}] must be object",
        )
        allowed_descriptor = {"path", "sha", "artifact"}
        _require(
            set(descriptor.keys()) <= allowed_descriptor
            and {"path", "sha"} <= set(descriptor.keys()),
            f"prepared_plan: work_unit_artifacts[{phase_id}] keys must include path+sha and only {sorted(allowed_descriptor)}",
        )
        _require(
            isinstance(descriptor["path"], str) and len(descriptor["path"]) > 0,
            f"prepared_plan: work_unit_artifacts[{phase_id}].path must be non-empty string",
        )
        _require(
            isinstance(descriptor["sha"], str) and bool(_SHA256_RE.match(descriptor["sha"])),
            f"prepared_plan: work_unit_artifacts[{phase_id}].sha must be sha256",
        )
        if "artifact" in descriptor:
            _require(
                descriptor["artifact"] is None or isinstance(descriptor["artifact"], Mapping),
                f"prepared_plan: work_unit_artifacts[{phase_id}].artifact must be object or null",
            )

    # acceptance: null or shaped object.
    acceptance = payload["acceptance"]
    if acceptance is not None:
        _require(
            isinstance(acceptance, Mapping),
            "prepared_plan: acceptance must be null or object",
        )
        required_acc = {
            "accepted_by",
            "accepted_at",
            "accepted_source_sha",
            "accepted_prepared_sha",
        }
        _require(
            set(acceptance.keys()) == required_acc,
            f"prepared_plan: acceptance keys must be exactly {sorted(required_acc)}",
        )
        _require(
            isinstance(acceptance["accepted_by"], str) and len(acceptance["accepted_by"]) > 0,
            "prepared_plan: acceptance.accepted_by must be non-empty string",
        )
        _require(
            isinstance(acceptance["accepted_at"], str) and len(acceptance["accepted_at"]) > 0,
            "prepared_plan: acceptance.accepted_at must be non-empty string",
        )
        for sha_field in ("accepted_source_sha", "accepted_prepared_sha"):
            _require(
                isinstance(acceptance[sha_field], str)
                and bool(_SHA256_RE.match(acceptance[sha_field])),
                f"prepared_plan: acceptance.{sha_field} must be sha256",
            )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _run_dir(*, run_id: str, data_dir: Path | None) -> Path:
    base = Path(data_dir) if data_dir else resolve_data_dir()
    return base / "runs" / run_id


def _artifact_path(*, run_id: str, data_dir: Path | None) -> Path:
    return _run_dir(run_id=run_id, data_dir=data_dir) / _ARTIFACT_NAME


def _round_trip_paths(payload: Mapping[str, Any], *, repo_root: Path) -> None:
    """Round-trip every path field through canonicalize() (fail-closed)."""

    for key in _PATH_FIELDS:
        canonicalize(payload[key], repo_root=repo_root)
    canonicalize(payload["inspect_artifact"]["path"], repo_root=repo_root)
    for phase_id, descriptor in payload["work_unit_artifacts"].items():
        canonicalize(descriptor["path"], repo_root=repo_root)


def _resolve_repo_root(payload: Mapping[str, Any], *, repo_root: Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    declared = payload.get("repo_root")
    if isinstance(declared, str) and declared:
        candidate = Path(declared)
        if candidate.is_absolute():
            return candidate
    return REPO_ROOT


def write_prepared_artifact(
    *,
    run_id: str,
    payload: Mapping[str, Any],
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Validate, trust-boundary-check, and atomically write the artifact."""

    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    # We work on a shallow copy so callers cannot observe in-flight mutation.
    snapshot = dict(payload)
    _validate_against_schema(snapshot)
    _round_trip_paths(snapshot, repo_root=_resolve_repo_root(snapshot, repo_root=repo_root))
    path = _artifact_path(run_id=run_id, data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, snapshot)
    return path


def load_prepared_artifact(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Read + schema-lint + trust-boundary the artifact.

    Fails closed before returning. Raises ``FileNotFoundError`` if the
    artifact is missing.
    """

    path = _artifact_path(run_id=run_id, data_dir=data_dir)
    if not path.is_file():
        raise FileNotFoundError(f"prepared_plan artifact not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prepared_plan artifact must decode to a JSON object")
    _validate_against_schema(payload)
    _round_trip_paths(payload, repo_root=_resolve_repo_root(payload, repo_root=repo_root))
    return payload


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def mark_ready_for_acceptance(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Promote a draft / needs_input artifact to ready_for_acceptance.

    Both ``draft`` and ``needs_input`` are accepted source states (the
    needs_input case represents a fix-loop returning to ready).
    """

    payload = load_prepared_artifact(run_id, data_dir=data_dir, repo_root=repo_root)
    current = payload["status"]
    if current not in {STATUS_DRAFT, STATUS_NEEDS_INPUT}:
        raise InvalidPreparedTransition(
            f"mark_ready_for_acceptance: cannot transition from {current!r} to ready_for_acceptance"
        )
    payload["status"] = STATUS_READY
    payload["ready_at"] = utc_now()
    return write_prepared_artifact(
        run_id=run_id, payload=payload, data_dir=data_dir, repo_root=repo_root
    )


def accept_prepared(
    run_id: str,
    *,
    accepted_by: str = "human",
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Flip status to ``accepted`` IFF current status is ready_for_acceptance.

    Re-runs schema + trust-boundary checks via load_prepared_artifact, then
    re-runs stale detection (fail-closed) before mutating status. This is
    the ONLY function that may flip status to ``accepted``.
    """

    payload = load_prepared_artifact(run_id, data_dir=data_dir, repo_root=repo_root)
    current = payload["status"]
    if current != STATUS_READY:
        raise InvalidPreparedTransition(
            f"accept_prepared: cannot accept from status {current!r}; "
            f"expected {STATUS_READY!r}"
        )
    resolved_root = _resolve_repo_root(payload, repo_root=repo_root)
    drift = check_stale(payload, repo_root=resolved_root)
    if drift is not None:
        raise ValueError(
            f"accept_prepared: prepared artifact is stale: {drift.reasons}"
        )
    now = utc_now()
    payload["status"] = STATUS_ACCEPTED
    payload["accepted_at"] = now
    payload["acceptance"] = {
        "accepted_by": accepted_by,
        "accepted_at": now,
        "accepted_source_sha": payload["source_plan_sha"],
        "accepted_prepared_sha": payload["prepared_plan_sha"],
    }
    return write_prepared_artifact(
        run_id=run_id, payload=payload, data_dir=data_dir, repo_root=repo_root
    )


_REJECT_FROM_STATES = frozenset(
    {STATUS_DRAFT, STATUS_READY, STATUS_NEEDS_INPUT, STATUS_STALE}
)


def reject_prepared(
    run_id: str,
    *,
    reason: str = "",
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Mark an artifact as ``rejected``.

    Allowed source states (Phase 1 coordinator decision Q3):
    ``draft``, ``ready_for_acceptance``, ``needs_input``, ``stale``.
    Calling from ``accepted`` or ``rejected`` is an idempotent no-op:
    returns the existing artifact path without mutating state. This avoids
    surprising errors when a rejection request races with another agent
    finalizing the run.
    """

    payload = load_prepared_artifact(run_id, data_dir=data_dir, repo_root=repo_root)
    current = payload["status"]
    if current in {STATUS_ACCEPTED, STATUS_REJECTED}:
        return _artifact_path(run_id=run_id, data_dir=data_dir)
    if current not in _REJECT_FROM_STATES:
        # Defensive: any unknown status should fail closed.
        raise InvalidPreparedTransition(
            f"reject_prepared: cannot reject from status {current!r}"
        )
    payload["status"] = STATUS_REJECTED
    if reason:
        payload["rejection_reason"] = reason
    return write_prepared_artifact(
        run_id=run_id, payload=payload, data_dir=data_dir, repo_root=repo_root
    )


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StaleReason:
    """Sentinel returned by :func:`check_stale` when drift is detected."""

    reasons: tuple[str, ...]


def _git_head_sha(repo_root: Path, ref: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def check_stale(
    artifact: Mapping[str, Any],
    *,
    repo_root: Path,
) -> StaleReason | None:
    """Detect drift across the four sources defined in AC #3.

    Drift sources surfaced as string keys (mirrors resume.py:140 idiom):

    * ``source_plan_sha`` -- whole-plan content drift.
    * ``prepared_plan_sha`` -- sidecar prepared-plan content drift.
    * ``git_base_sha`` -- base ref moved (or git unavailable).
    * ``phase:<phase_id>`` -- per-phase cache_key drift.

    All sources are checked (no short-circuit) so the operator sees the
    full set in one pass. Returns ``None`` when no drift is detected.
    """

    drift: list[str] = []
    root = Path(repo_root)

    # 1. whole source-plan sha
    source_plan_path = root / artifact["source_plan_path"]
    if not source_plan_path.is_file():
        drift.append("source_plan_path_missing")
    else:
        if _sha256_file(source_plan_path) != artifact["source_plan_sha"]:
            drift.append("source_plan_sha")

    # 2. sidecar prepared-plan sha
    prepared_plan_path = root / artifact["prepared_plan_path"]
    if not prepared_plan_path.is_file():
        drift.append("prepared_plan_path_missing")
    else:
        if _sha256_file(prepared_plan_path) != artifact["prepared_plan_sha"]:
            drift.append("prepared_plan_sha")

    # 3. git base sha
    head = _git_head_sha(root, artifact["git_base_ref"])
    if head is None:
        drift.append("git_base_sha_unavailable")
    elif head != artifact["git_base_sha"]:
        drift.append("git_base_sha")

    # 4. per-phase cache_key drift
    if source_plan_path.is_file():
        try:
            current_text = source_plan_path.read_text(encoding="utf-8")
        except OSError:
            current_text = ""
        for phase in artifact["phase_map"]:
            recomputed = _compute_cache_key(
                content_sha=_sha256_bytes(current_text.encode("utf-8")),
                prepared_plan_sha=artifact["prepared_plan_sha"],
                plan_context_sha=phase["plan_context_sha"],
            )
            if recomputed != phase["cache_key"]:
                drift.append(f"phase:{phase['phase_id']}")

    if drift:
        return StaleReason(tuple(drift))
    return None


__all__ = [
    "InvalidPreparedTransition",
    "PREPARE_POLICY_VERSION",
    "SCHEMA_VERSION",
    "STATUS_ACCEPTED",
    "STATUS_DRAFT",
    "STATUS_NEEDS_INPUT",
    "STATUS_READY",
    "STATUS_REJECTED",
    "STATUS_STALE",
    "StaleReason",
    "WORK_UNITS_SCHEMA_VERSION",
    "accept_prepared",
    "canonicalize",
    "check_stale",
    "load_prepared_artifact",
    "mark_ready_for_acceptance",
    "reject_prepared",
    "write_prepared_artifact",
]
