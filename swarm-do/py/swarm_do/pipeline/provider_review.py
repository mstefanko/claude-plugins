"""Internal read-only provider review runner.

The real Claude/Codex shims intentionally fail closed until Phase 0 proves the
exact structured-output and write-denial gates. The fake shim path is the
deterministic harness used by unit tests and local DSL/doctor validation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping, Sequence

from swarm_do.telemetry.extractors.hashing import stable_finding_hash_v1
from swarm_do.telemetry.extractors.paths import normalize_path
from swarm_do.telemetry.ids import new_ulid
from swarm_do.telemetry.schemas import validate_value

from .paths import REPO_ROOT, resolve_data_dir
from .resolver import BackendResolver, Route


SCHEMA_VERSION = "provider-findings.v2-draft"
CONSENSUS_POLICY_VERSION = "provider-review.consensus-policy.v1"
CONSENSUS_CALIBRATION_SAMPLE_SCHEMA_VERSION = "provider-review.consensus-calibration.samples.v1"
CONSENSUS_CALIBRATION_REPORT_SCHEMA_VERSION = "provider-review.consensus-calibration.v1"
EMISSION_SCHEMA_PATH = REPO_ROOT / "schemas" / "provider_review" / "review_emission.v1.schema.json"
PROVIDER_FINDINGS_V2_SCHEMA_PATH = REPO_ROOT / "schemas" / "telemetry" / "provider_findings.v2.schema.json"
KNOWN_REVIEW_SHIMS = ("claude", "codex", "gemini")
SELECTIONS = {"auto", "explicit", "off"}
DEFAULT_MAX_PARALLEL = 4
DEFAULT_MIN_SUCCESS = 1
DOCTOR_CACHE_FILENAME = "provider-review-doctor-cache.json"
DEFAULT_ROLE = "agent-review"
NATIVE_SCHEMA_MODE = "native"
PARSER_FALLBACK_SCHEMA_MODE = "parser-fallback"
PARSER_FALLBACK_CONFIDENCE_CAP = 0.65
DEFAULT_CODEX_R2_TIMEOUT_SECONDS = 90
DEFAULT_CLAUDE_R3_TIMEOUT_SECONDS = 90
DEFAULT_AUTH_PROBE_TIMEOUT_SECONDS = 10
MAX_NORMALIZED_FINDINGS = 5
CODEX_WRITE_DENIAL_CREATE_PATH = "codex-created.txt"
CODEX_WRITE_DENIAL_EDIT_PATH = "codex-edit-target.txt"
CODEX_WRITE_DENIAL_DELETE_PATH = "codex-delete-target.txt"
CODEX_WRITE_DENIAL_EDIT_ORIGINAL = "original edit target\n"
CODEX_WRITE_DENIAL_DELETE_ORIGINAL = "original delete target\n"
CLAUDE_WRITE_DENIAL_CREATE_PATH = "claude-created.txt"
CLAUDE_WRITE_DENIAL_EDIT_PATH = "claude-edit-target.txt"
CLAUDE_WRITE_DENIAL_DELETE_PATH = "claude-delete-target.txt"
CLAUDE_WRITE_DENIAL_EDIT_ORIGINAL = "original edit target\n"
CLAUDE_WRITE_DENIAL_DELETE_ORIGINAL = "original delete target\n"
_SEVERITY_MAP = {
    "warning": "high",
    "error": "critical",
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "info",
}
_CATEGORY_REWRITES = {"types": "types_or_null", "null": "types_or_null"}
_LEADING_VERB_RE = re.compile(r"^[A-Z][a-z]*[a-z] ")
_SAFE_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HELP_FLAG_RE = re.compile(r"(?<![A-Za-z0-9_-])--?[A-Za-z0-9][A-Za-z0-9-]*(?![A-Za-z0-9_-])")
_FALLBACK_LINE_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])\s*"
    r"(?:\[(?P<severity>[A-Za-z]+)(?:\s*\|\s*[A-Za-z]+)?\]\s*)?"
    r"(?P<location>[^:\n]+:\d+(?:-\d+)?)\s*(?:-|:)\s*(?P<summary>.+?)\s*$"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|auth[_-]?token|credential|password|passwd|secret)\b"
    r"\s*[:=]\s*([\"']?)[^\s,\"';]+",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_OPENAI_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\bA(?:KIA|SIA)[0-9A-Z]{16}\b")
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class ProviderReviewError(ValueError):
    """Raised when provider review input or output cannot satisfy the contract."""


class ProviderReviewSchemaError(ProviderReviewError):
    """Raised when normalized provider-review artifacts violate v2 schema."""


@dataclasses.dataclass(frozen=True)
class ReviewProviderPolicy:
    selection: str = "auto"
    min_success: int = DEFAULT_MIN_SUCCESS
    max_parallel: int = DEFAULT_MAX_PARALLEL
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    enabled: Mapping[str, bool] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection,
            "min_success": self.min_success,
            "max_parallel": self.max_parallel,
            "include": list(self.include),
            "exclude": list(self.exclude),
            "enabled": dict(self.enabled),
        }


@dataclasses.dataclass(frozen=True)
class ReviewProviderProbeCheck:
    status: str
    ready: bool
    reason: str
    data: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "status": self.status,
            "ready": self.ready,
            "reason": self.reason,
        }
        if self.data:
            row["data"] = dict(self.data)
        return row


@dataclasses.dataclass(frozen=True)
class ReviewProviderProbe:
    provider_id: str
    configured: ReviewProviderProbeCheck
    installed: ReviewProviderProbeCheck
    schema: ReviewProviderProbeCheck
    read_only: ReviewProviderProbeCheck
    auth: ReviewProviderProbeCheck
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return (
            self.configured.ready
            and self.installed.ready
            and self.schema.ready
            and self.read_only.ready
            and self.auth.ready
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "ready": self.ready,
            "configured": self.configured.as_dict(),
            "installed": self.installed.as_dict(),
            "schema": self.schema.as_dict(),
            "read_only": self.read_only.as_dict(),
            "auth": self.auth.as_dict(),
            "blockers": list(self.blockers),
        }


@dataclasses.dataclass(frozen=True)
class ReviewProviderStatus:
    provider_id: str
    status: str
    reason: str
    eligible: bool
    route: Mapping[str, Any] | None = None
    executable: str | None = None
    cli_version: str | None = None
    schema_mode: str = "unavailable"
    read_only_mode: str = "unavailable"
    schema_flags: tuple[str, ...] = ()
    read_only_flags: tuple[str, ...] = ()
    missing_schema_flags: tuple[str, ...] = ()
    missing_read_only_flags: tuple[str, ...] = ()
    fake: bool = False
    probe: ReviewProviderProbe | None = None

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "provider_id": self.provider_id,
            "status": self.status,
            "reason": self.reason,
            "eligible": self.eligible,
            "schema_mode": self.schema_mode,
            "read_only_mode": self.read_only_mode,
            "schema_flags": list(self.schema_flags),
            "read_only_flags": list(self.read_only_flags),
            "missing_schema_flags": list(self.missing_schema_flags),
            "missing_read_only_flags": list(self.missing_read_only_flags),
            "fake": self.fake,
        }
        if self.route is not None:
            row["route"] = dict(self.route)
        if self.executable:
            row["executable"] = self.executable
        if self.cli_version:
            row["cli_version"] = self.cli_version
        if self.probe is not None:
            row["probe"] = self.probe.as_dict()
        return row


@dataclasses.dataclass(frozen=True)
class ReviewSelectionResult:
    policy: ReviewProviderPolicy
    configured_providers: tuple[str, ...]
    eligible_providers: tuple[str, ...]
    selected_providers: tuple[str, ...]
    skipped_providers: tuple[ReviewProviderStatus, ...]
    provider_statuses: tuple[ReviewProviderStatus, ...]
    selection_result: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.as_dict(),
            "configured_providers": list(self.configured_providers),
            "eligible_providers": list(self.eligible_providers),
            "selected_providers": list(self.selected_providers),
            "skipped_providers": [status.as_dict() for status in self.skipped_providers],
            "provider_statuses": [status.as_dict() for status in self.provider_statuses],
            "selection_result": self.selection_result,
        }


@dataclasses.dataclass(frozen=True)
class ProviderRunResult:
    provider_id: str
    payload: Any | None
    stdout_text: str
    stderr_text: str
    error_class: str | None = None
    message: str | None = None
    schema_mode: str = "native"
    elapsed_seconds: float = 0.0
    sidecar_path: str | None = None
    last_message_text: str | None = None
    command_argv: tuple[str, ...] = ()
    returncode: int | None = None

    @property
    def ok(self) -> bool:
        return self.error_class is None


@dataclasses.dataclass(frozen=True)
class ProviderFixtureResult:
    name: str
    status: str
    ready: bool
    reason: str
    command_argv: tuple[str, ...] = ()
    returncode: int | None = None
    stdout_text: str = ""
    stderr_text: str = ""
    data: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def as_probe_check(self) -> ReviewProviderProbeCheck:
        data: dict[str, Any] = dict(self.data)
        if self.command_argv:
            data["command_argv"] = _redacted_argv(self.command_argv)
        if self.returncode is not None:
            data["returncode"] = self.returncode
        if self.stdout_text:
            data["stdout_snippet"] = _text_snippet(self.stdout_text)
        if self.stderr_text:
            data["stderr_snippet"] = _text_snippet(self.stderr_text)
        if self.stdout_text or self.stderr_text:
            data["diagnostic_snippets_sensitive"] = True
        return ReviewProviderProbeCheck(
            status=self.status,
            ready=self.ready,
            reason=self.reason,
            data=data,
        )


CodexProbeResult = ProviderFixtureResult
ClaudeProbeResult = ProviderFixtureResult


def _iso_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text_snippet(text: str, limit: int = 1000) -> str:
    return _redact_sensitive_text(text)[:limit]


def _redact_sensitive_text(text: str) -> str:
    redacted = _PRIVATE_KEY_RE.sub("<redacted-private-key>", text)
    redacted = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    redacted = _BEARER_TOKEN_RE.sub("Bearer <redacted>", redacted)
    redacted = _OPENAI_TOKEN_RE.sub("sk-<redacted>", redacted)
    redacted = _GITHUB_TOKEN_RE.sub("gh<redacted>", redacted)
    redacted = _AWS_ACCESS_KEY_RE.sub("<redacted-aws-access-key>", redacted)
    return redacted


def _load_json_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ProviderReviewSchemaError(f"{path} did not contain a JSON object")
    return value


def load_emission_schema() -> dict[str, Any]:
    return _load_json_schema(EMISSION_SCHEMA_PATH)


def load_provider_findings_v2_schema() -> dict[str, Any]:
    return _load_json_schema(PROVIDER_FINDINGS_V2_SCHEMA_PATH)


def minified_emission_schema() -> str:
    return json.dumps(load_emission_schema(), separators=(",", ":"), sort_keys=True)


def validate_emission_payload(payload: Mapping[str, Any]) -> None:
    errors = validate_value(dict(payload), load_emission_schema())
    if errors:
        raise ProviderReviewSchemaError("provider review emission schema violation: " + "; ".join(errors[:5]))


def validate_provider_findings_v2_artifact(payload: Mapping[str, Any]) -> None:
    errors = validate_value(dict(payload), load_provider_findings_v2_schema())
    if errors:
        raise ProviderReviewSchemaError("provider-findings v2 schema violation: " + "; ".join(errors[:5]))


def consensus_policy() -> dict[str, Any]:
    return {
        "policy_version": CONSENSUS_POLICY_VERSION,
        "confirmed_requires": "exact stable-hash agreement from at least two schema-valid providers with consensus_score >= 0.75",
        "secondary_cluster_promotion": "disabled",
        "single_provider_findings": "needs-verification",
        "stock_auto_min_success": DEFAULT_MIN_SUCCESS,
        "calibration_status": "conservative-no-secondary-promotion",
    }


def parse_provider_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    providers = tuple(part.strip() for part in raw.split(",") if part.strip())
    for provider_id in providers:
        if not _SAFE_PROVIDER_RE.fullmatch(provider_id):
            raise ProviderReviewError(f"invalid provider id: {provider_id!r}")
    return providers


def review_doctor_cache_path() -> Path:
    return resolve_data_dir() / DOCTOR_CACHE_FILENAME


def load_review_doctor_cache() -> dict[str, Any] | None:
    path = review_doctor_cache_path()
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_review_doctor_cache(payload: Mapping[str, Any]) -> Path:
    path = review_doctor_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, dict(payload))
    return path


def _detected_required_flags(help_text: str, required_flags: Sequence[str]) -> tuple[str, ...]:
    tokens = set(_HELP_FLAG_RE.findall(help_text))
    return tuple(flag for flag in required_flags if flag in tokens)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return parse_provider_csv(value)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                continue
            out.append(item.strip())
        return tuple(out)
    return ()


def _policy_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum:
        return value
    return default


def _merge_policy(base: Mapping[str, Any] | None, preset: Mapping[str, Any] | None) -> ReviewProviderPolicy:
    base = base if isinstance(base, Mapping) else {}
    preset = preset if isinstance(preset, Mapping) else {}
    selection = str(preset.get("selection", base.get("selection", "auto")))
    if selection not in SELECTIONS:
        selection = "auto"
    min_success = _policy_int(preset.get("min_success", base.get("min_success")), DEFAULT_MIN_SUCCESS, minimum=1, maximum=32)
    max_parallel = _policy_int(preset.get("max_parallel", base.get("max_parallel")), DEFAULT_MAX_PARALLEL, minimum=1, maximum=32)
    include = _as_str_tuple(preset.get("include", base.get("include")))
    exclude = _as_str_tuple(preset.get("exclude", base.get("exclude")))
    enabled: dict[str, bool] = {}
    for table in (base,):
        for key, value in table.items():
            if isinstance(value, Mapping) and isinstance(value.get("enabled"), bool):
                enabled[str(key)] = bool(value["enabled"])
    return ReviewProviderPolicy(selection, min_success, max_parallel, include, exclude, enabled)


def _probe_check(status: str, ready: bool, reason: str, data: Mapping[str, Any] | None = None) -> ReviewProviderProbeCheck:
    return ReviewProviderProbeCheck(status=status, ready=ready, reason=reason, data=dict(data or {}))


def _augment_probe_check(check: ReviewProviderProbeCheck, data: Mapping[str, Any]) -> ReviewProviderProbeCheck:
    merged = dict(data)
    merged.update(check.data)
    return dataclasses.replace(check, data=merged)


def _skipped_probe_check(reason: str) -> ReviewProviderProbeCheck:
    return _probe_check("skipped", False, reason)


def _probe_blockers(
    *,
    configured: ReviewProviderProbeCheck,
    installed: ReviewProviderProbeCheck,
    schema: ReviewProviderProbeCheck,
    read_only: ReviewProviderProbeCheck,
    auth: ReviewProviderProbeCheck,
) -> tuple[str, ...]:
    blockers: list[str] = []
    for name, check in (
        ("configured", configured),
        ("installed", installed),
        ("schema", schema),
        ("read_only", read_only),
        ("auth", auth),
    ):
        if not check.ready:
            blockers.append(name)
    return tuple(blockers)


def _probe_reason(probe: ReviewProviderProbe) -> str:
    reasons = []
    for name in ("configured", "installed", "schema", "read_only", "auth"):
        check = getattr(probe, name)
        if not check.ready:
            reasons.append(check.reason)
    return "; ".join(reasons) or "ready"


def _make_probe(
    provider_id: str,
    *,
    configured: ReviewProviderProbeCheck,
    installed: ReviewProviderProbeCheck,
    schema: ReviewProviderProbeCheck,
    read_only: ReviewProviderProbeCheck,
    auth: ReviewProviderProbeCheck,
) -> ReviewProviderProbe:
    return ReviewProviderProbe(
        provider_id=provider_id,
        configured=configured,
        installed=installed,
        schema=schema,
        read_only=read_only,
        auth=auth,
        blockers=_probe_blockers(
            configured=configured,
            installed=installed,
            schema=schema,
            read_only=read_only,
            auth=auth,
        ),
    )


def _fake_provider_ids_from_env() -> tuple[str, ...]:
    return parse_provider_csv(os.environ.get("SWARM_PROVIDER_REVIEW_FAKE_PROVIDERS"))


class ReviewProviderResolver:
    """Resolve configured review shims and select eligible providers."""

    def __init__(
        self,
        *,
        preset_name: str | None = "current",
        preset_data: Mapping[str, Any] | None = None,
        base_backends_path: Path | None = None,
        which: Callable[[str], str | None] = shutil.which,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        fake_providers: Sequence[str] | None = None,
        claude_read_only_probe: ReviewProviderProbeCheck | None = None,
        claude_auth_probe: ReviewProviderProbeCheck | None = None,
        codex_schema_probe: ReviewProviderProbeCheck | None = None,
        codex_read_only_probe: ReviewProviderProbeCheck | None = None,
        codex_auth_probe: ReviewProviderProbeCheck | None = None,
    ):
        self.backend_resolver = BackendResolver(
            preset_name=preset_name,
            preset_data=preset_data,
            base_backends_path=base_backends_path,
        )
        self.which = which
        self.runner = runner
        self.fake_providers = tuple(fake_providers) if fake_providers is not None else _fake_provider_ids_from_env()
        self.claude_read_only_probe = claude_read_only_probe
        self.claude_auth_probe = claude_auth_probe
        self.codex_schema_probe = codex_schema_probe
        self.codex_read_only_probe = codex_read_only_probe
        self.codex_auth_probe = codex_auth_probe
        self.policy = _merge_policy(
            self.backend_resolver.base.get("review_providers"),
            self.backend_resolver.preset.get("review_providers"),
        )

    def known_provider_ids(self, explicit: Sequence[str] = ()) -> tuple[str, ...]:
        ordered: list[str] = []
        for provider_id in (*KNOWN_REVIEW_SHIMS, *self.fake_providers, *explicit):
            if provider_id not in ordered:
                ordered.append(provider_id)
        return tuple(ordered)

    def statuses(self, explicit: Sequence[str] = ()) -> tuple[ReviewProviderStatus, ...]:
        return tuple(self._status_for(provider_id) for provider_id in self.known_provider_ids(explicit))

    def select(
        self,
        *,
        selection: str | None = None,
        explicit_providers: Sequence[str] = (),
        max_parallel: int | None = None,
    ) -> ReviewSelectionResult:
        requested_selection = selection or self.policy.selection
        if requested_selection not in SELECTIONS:
            raise ProviderReviewError(f"selection must be one of {sorted(SELECTIONS)}")
        explicit = tuple(explicit_providers)
        statuses = self.statuses(explicit)
        status_by_id = {status.provider_id: status for status in statuses}
        max_selected = max_parallel if isinstance(max_parallel, int) and max_parallel > 0 else self.policy.max_parallel

        configured: list[str] = []
        for status in statuses:
            if self.policy.enabled.get(status.provider_id) is False:
                continue
            if self.policy.include and status.provider_id not in self.policy.include:
                continue
            if status.provider_id in self.policy.exclude:
                continue
            configured.append(status.provider_id)

        if requested_selection == "off":
            selected: list[str] = []
            result = "off"
        elif requested_selection == "explicit":
            candidates = list(explicit or self.policy.include)
            configured = [provider_id for provider_id in candidates if provider_id in status_by_id]
            selected = [
                provider_id
                for provider_id in configured
                if status_by_id[provider_id].eligible and provider_id not in self.policy.exclude
            ][:max_selected]
            result = "selected" if selected else "no explicit providers eligible"
        else:
            selected = [
                provider_id
                for provider_id in configured
                if status_by_id[provider_id].eligible
            ][:max_selected]
            result = "selected" if selected else "no eligible providers"

        eligible = tuple(status.provider_id for status in statuses if status.eligible)
        skipped = tuple(status for status in statuses if status.provider_id not in selected)
        return ReviewSelectionResult(
            policy=dataclasses.replace(self.policy, selection=requested_selection, max_parallel=max_selected),
            configured_providers=tuple(configured),
            eligible_providers=eligible,
            selected_providers=tuple(selected),
            skipped_providers=skipped,
            provider_statuses=statuses,
            selection_result=result,
        )

    def _status_for(self, provider_id: str) -> ReviewProviderStatus:
        if provider_id in self.fake_providers:
            probe = _make_probe(
                provider_id,
                configured=_probe_check("ok", True, "fake shim enabled for deterministic provider-review tests"),
                installed=_probe_check("ok", True, "fake shim does not require a local executable"),
                schema=_probe_check("ok", True, "fake shim emits native test fixtures", {"schema_mode": "native"}),
                read_only=_probe_check("ok", True, "fake shim reads local fixture files only", {"read_only_mode": "confirmed"}),
                auth=_probe_check("ok", True, "fake shim does not require provider authentication"),
            )
            return ReviewProviderStatus(
                provider_id=provider_id,
                status="eligible",
                reason="fake shim enabled for deterministic provider-review tests",
                eligible=True,
                executable=f"fake://{provider_id}",
                cli_version="fake-shim",
                schema_mode="native",
                read_only_mode="confirmed",
                fake=True,
                probe=probe,
            )
        if self.policy.enabled.get(provider_id) is False:
            probe = _make_probe(
                provider_id,
                configured=_probe_check("skipped", False, "disabled by review_providers config"),
                installed=_skipped_probe_check("not checked because provider is disabled"),
                schema=_skipped_probe_check("not checked because provider is disabled"),
                read_only=_skipped_probe_check("not checked because provider is disabled"),
                auth=_skipped_probe_check("not checked because provider is disabled"),
            )
            return ReviewProviderStatus(provider_id, "skipped", _probe_reason(probe), False, probe=probe)
        if provider_id == "claude":
            return self._real_cli_status(
                provider_id="claude",
                role="agent-review",
                executable_name="claude",
                required_schema_flags=("-p", "--json-schema", "--output-format"),
                required_read_only_flags=("--permission-mode",),
                read_only_probe=self.claude_read_only_probe,
                read_only_probe_required_reason="read-only flags detected but Phase R3 write-denial proof not complete",
                auth_probe=self.claude_auth_probe,
            )
        if provider_id == "codex":
            return self._real_cli_status(
                provider_id="codex",
                role="agent-codex-review",
                executable_name="codex",
                required_schema_flags=("--json", "--output-schema", "--output-last-message"),
                required_read_only_flags=("--sandbox",),
                schema_probe=self.codex_schema_probe,
                schema_probe_required_reason="structured-output flags detected but Phase R2 schema smoke proof not complete",
                read_only_probe=self.codex_read_only_probe,
                read_only_probe_required_reason="read-only flags detected but Phase R2 write-denial proof not complete",
                auth_probe=self.codex_auth_probe,
            )
        if provider_id == "gemini":
            path = self.which("gemini")
            installed = (
                _probe_check("ok", True, "gemini found on PATH", {"path": path})
                if path
                else _probe_check("skipped", False, "gemini not found on PATH")
            )
            probe = _make_probe(
                provider_id,
                configured=_probe_check("skipped", False, "gemini shim is reserved but not implemented"),
                installed=installed,
                schema=_probe_check("error", False, "native schema mode unavailable; gemini shim not implemented", {"schema_mode": "unavailable"}),
                read_only=_skipped_probe_check("not checked because gemini shim is not implemented"),
                auth=_skipped_probe_check("not checked because gemini shim is not implemented"),
            )
            return ReviewProviderStatus(
                provider_id,
                "skipped",
                _probe_reason(probe),
                False,
                executable=path,
                probe=probe,
            )
        probe = _make_probe(
            provider_id,
            configured=_probe_check("skipped", False, "no shim registered for provider"),
            installed=_skipped_probe_check("not checked because no shim is registered"),
            schema=_skipped_probe_check("not checked because no shim is registered"),
            read_only=_skipped_probe_check("not checked because no shim is registered"),
            auth=_skipped_probe_check("not checked because no shim is registered"),
        )
        return ReviewProviderStatus(provider_id, "skipped", _probe_reason(probe), False, probe=probe)

    def _real_cli_status(
        self,
        *,
        provider_id: str,
        role: str,
        executable_name: str,
        required_schema_flags: Sequence[str],
        required_read_only_flags: Sequence[str],
        schema_probe: ReviewProviderProbeCheck | None = None,
        schema_probe_required_reason: str | None = None,
        read_only_probe: ReviewProviderProbeCheck | None = None,
        read_only_probe_required_reason: str | None = None,
        auth_probe: ReviewProviderProbeCheck | None = None,
    ) -> ReviewProviderStatus:
        route: Route | None = None
        try:
            route = self.backend_resolver.resolve(role, "hard")
        except Exception as exc:
            configured = _probe_check("error", False, f"route resolution failed: {exc}")
        else:
            configured = (
                _probe_check("ok", True, f"{role} route resolves to {provider_id}", {"route": route.as_dict()})
                if route.backend == provider_id
                else _probe_check(
                    "skipped",
                    False,
                    f"role route resolves to backend {route.backend}, not {provider_id}",
                    {"route": route.as_dict()},
                )
            )

        path = self.which(executable_name)
        if not path:
            installed = _probe_check("skipped", False, f"{executable_name} not found on PATH")
            help_text = ""
            version = None
        else:
            installed = _probe_check("ok", True, f"{executable_name} found on PATH", {"path": path})
            help_text = self._help_text(executable_name)
            version = self._version_text(executable_name)

        schema_flags = _detected_required_flags(help_text, required_schema_flags) if path else ()
        read_only_flags = _detected_required_flags(help_text, required_read_only_flags) if path else ()
        missing_schema_flags = tuple(flag for flag in required_schema_flags if flag not in schema_flags)
        missing_read_only_flags = tuple(flag for flag in required_read_only_flags if flag not in read_only_flags)
        schema_ok = not missing_schema_flags
        read_only_ok = not missing_read_only_flags
        schema_mode = "native" if schema_ok else "unavailable"
        read_only_mode = "flag-detected" if read_only_ok else "unavailable"
        effective_read_only_mode = read_only_mode

        if not path:
            schema = _skipped_probe_check("not checked because provider executable is unavailable")
            read_only = _skipped_probe_check("not checked because provider executable is unavailable")
        else:
            schema_data = {"schema_mode": schema_mode, "flags": list(schema_flags), "missing_flags": []}
            if not schema_ok:
                schema = _probe_check(
                    "error",
                    False,
                    "structured-output flags not detected: " + ", ".join(missing_schema_flags),
                    {"schema_mode": schema_mode, "flags": list(schema_flags), "missing_flags": list(missing_schema_flags)},
                )
            elif schema_probe is not None:
                schema = _augment_probe_check(schema_probe, schema_data)
            elif schema_probe_required_reason is not None:
                schema = _probe_check(
                    "warning",
                    False,
                    schema_probe_required_reason,
                    schema_data,
                )
            else:
                schema = _probe_check(
                    "ok",
                    True,
                    "native structured-output flags detected",
                    schema_data,
                )
            read_only_data = {"read_only_mode": read_only_mode, "flags": list(read_only_flags), "missing_flags": []}
            if not read_only_ok:
                read_only = _probe_check(
                    "error",
                    False,
                    "read-only flags not detected: " + ", ".join(missing_read_only_flags),
                    {"read_only_mode": read_only_mode, "flags": list(read_only_flags), "missing_flags": list(missing_read_only_flags)},
                )
            else:
                if read_only_probe is not None and read_only_probe.ready:
                    effective_read_only_mode = "confirmed"
                    read_only_data["read_only_mode"] = effective_read_only_mode
                if read_only_probe is not None:
                    read_only = _augment_probe_check(read_only_probe, read_only_data)
                else:
                    read_only = _probe_check(
                        "warning",
                        False,
                        read_only_probe_required_reason
                        or "read-only flags detected but Phase 0 write-denial proof not complete",
                        read_only_data,
                    )
        if not path:
            auth = _skipped_probe_check("not checked because provider executable is unavailable")
        elif not configured.ready:
            auth = _skipped_probe_check("not checked because provider route is not configured for this shim")
        elif auth_probe is not None:
            auth = _augment_probe_check(auth_probe, {"probe_mode": "injected"})
        else:
            auth = self._auth_status_probe(provider_id, executable_name)
        probe = _make_probe(
            provider_id,
            configured=configured,
            installed=installed,
            schema=schema,
            read_only=read_only,
            auth=auth,
        )
        if not configured.ready or not installed.ready:
            status = "skipped"
        else:
            status = "eligible" if probe.ready else "warning"
        return ReviewProviderStatus(
            provider_id,
            status,
            _probe_reason(probe),
            probe.ready,
            route=route.as_dict() if route is not None else None,
            executable=path,
            cli_version=version,
            schema_mode=schema_mode,
            read_only_mode=effective_read_only_mode,
            schema_flags=schema_flags,
            read_only_flags=read_only_flags,
            missing_schema_flags=missing_schema_flags,
            missing_read_only_flags=missing_read_only_flags,
            probe=probe,
        )

    def _help_text(self, executable_name: str) -> str:
        args = [executable_name, "exec", "--help"] if executable_name == "codex" else [executable_name, "--help"]
        try:
            completed = self.runner(args, text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (completed.stdout or "") + "\n" + (completed.stderr or "")

    def _version_text(self, executable_name: str) -> str | None:
        try:
            completed = self.runner([executable_name, "--version"], text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = (completed.stdout or completed.stderr or "").strip()
        return text or None

    def _auth_status_probe(self, provider_id: str, executable_name: str) -> ReviewProviderProbeCheck:
        if provider_id == "claude":
            return run_claude_auth_status_probe(
                claude_bin=executable_name,
                runner=self.runner,
                timeout_seconds=DEFAULT_AUTH_PROBE_TIMEOUT_SECONDS,
            )
        if provider_id == "codex":
            return run_codex_auth_status_probe(
                codex_bin=executable_name,
                runner=self.runner,
                timeout_seconds=DEFAULT_AUTH_PROBE_TIMEOUT_SECONDS,
            )
        return _probe_check("warning", False, f"no non-spend auth probe registered for {provider_id}", {"failure_class": "spend_probe_required"})


def _completed_output(completed: subprocess.CompletedProcess[str]) -> str:
    return ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()


def _unsupported_status_command(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "unknown command",
        "unrecognized command",
        "invalid subcommand",
        "no such command",
        "unexpected argument",
        "command not found",
    )
    return any(marker in lowered for marker in markers)


def _auth_probe_data(command: Sequence[str], completed: subprocess.CompletedProcess[str] | None = None, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"command_argv": _redacted_argv(command)}
    if completed is not None:
        data["returncode"] = completed.returncode
        output = _completed_output(completed)
        if output:
            data["output_snippet"] = _text_snippet(output)
    data.update({key: value for key, value in extra.items() if value is not None})
    return data


def run_claude_auth_status_probe(
    *,
    claude_bin: str = "claude",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: int = DEFAULT_AUTH_PROBE_TIMEOUT_SECONDS,
) -> ReviewProviderProbeCheck:
    """Run Claude's non-spend auth status probe."""

    if timeout_seconds < 1:
        raise ProviderReviewError("Claude auth status probe timeout must be >= 1")
    command = [claude_bin, "auth", "status", "--json"]
    try:
        completed = runner(command, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return _probe_check(
            "error",
            False,
            f"Claude auth status probe timed out after {timeout_seconds}s",
            {
                "command_argv": _redacted_argv(command),
                "failure_class": "launch_unavailable",
                "stdout_snippet": _text_snippet(str(exc.stdout or "")),
                "stderr_snippet": _text_snippet(str(exc.stderr or "")),
            },
        )
    except OSError as exc:
        return _probe_check(
            "error",
            False,
            f"Claude auth status probe failed to start: {exc}",
            {"command_argv": _redacted_argv(command), "failure_class": "launch_unavailable"},
        )

    output = _completed_output(completed)
    if completed.returncode != 0 and _unsupported_status_command(output):
        return _probe_check(
            "warning",
            False,
            "Claude CLI has no usable non-spend auth status probe; bounded spend probe required",
            _auth_probe_data(command, completed, failure_class="spend_probe_required"),
        )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    logged_in = payload.get("loggedIn")
    if logged_in is True:
        return _probe_check(
            "ok",
            True,
            "Claude auth status reports logged in",
            _auth_probe_data(
                command,
                completed,
                failure_class=None,
                auth_method=payload.get("authMethod"),
                api_provider=payload.get("apiProvider"),
            ),
        )
    if logged_in is False:
        return _probe_check(
            "warning",
            False,
            "Claude auth status reports not authenticated",
            _auth_probe_data(
                command,
                completed,
                failure_class="not_authenticated",
                auth_method=payload.get("authMethod"),
                api_provider=payload.get("apiProvider"),
            ),
        )
    return _probe_check(
        "warning",
        False,
        "Claude auth status did not prove authentication readiness",
        _auth_probe_data(command, completed, failure_class="not_authenticated"),
    )


def run_codex_auth_status_probe(
    *,
    codex_bin: str = "codex",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: int = DEFAULT_AUTH_PROBE_TIMEOUT_SECONDS,
) -> ReviewProviderProbeCheck:
    """Run Codex's non-spend login status probe."""

    if timeout_seconds < 1:
        raise ProviderReviewError("Codex auth status probe timeout must be >= 1")
    command = [codex_bin, "login", "status"]
    try:
        completed = runner(command, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return _probe_check(
            "error",
            False,
            f"Codex login status probe timed out after {timeout_seconds}s",
            {
                "command_argv": _redacted_argv(command),
                "failure_class": "launch_unavailable",
                "stdout_snippet": _text_snippet(str(exc.stdout or "")),
                "stderr_snippet": _text_snippet(str(exc.stderr or "")),
            },
        )
    except OSError as exc:
        return _probe_check(
            "error",
            False,
            f"Codex login status probe failed to start: {exc}",
            {"command_argv": _redacted_argv(command), "failure_class": "launch_unavailable"},
        )

    output = _completed_output(completed)
    lowered = output.lower()
    if completed.returncode != 0 and _unsupported_status_command(output):
        return _probe_check(
            "warning",
            False,
            "Codex CLI has no usable non-spend login status probe; bounded spend probe required",
            _auth_probe_data(command, completed, failure_class="spend_probe_required"),
        )
    negative_markers = ("not logged in", "not currently logged in", "not authenticated", "logged out")
    if any(marker in lowered for marker in negative_markers):
        return _probe_check(
            "warning",
            False,
            "Codex login status reports not authenticated",
            _auth_probe_data(command, completed, failure_class="not_authenticated"),
        )
    if completed.returncode == 0 and "logged in" in lowered:
        return _probe_check(
            "ok",
            True,
            "Codex login status reports logged in",
            _auth_probe_data(command, completed, failure_class=None),
        )
    return _probe_check(
        "warning",
        False,
        "Codex login status did not prove authentication readiness",
        _auth_probe_data(command, completed, failure_class="not_authenticated"),
    )


def build_codex_review_command(
    *,
    codex_bin: str,
    repo: Path,
    prompt: str,
    schema_file: Path,
    last_message_file: Path,
    route: Route | None = None,
) -> list[str]:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "-C",
        str(repo),
        "--output-schema",
        str(schema_file),
        "--output-last-message",
        str(last_message_file),
    ]
    if route is not None:
        command.extend(["-m", route.model])
        if route.effort != "none":
            command.extend(["-c", f'model_reasoning_effort="{route.effort}"'])
    command.append(prompt)
    return command


def _ensure_probe_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        # Codex is invoked with -C against this directory. A real git init is
        # best, but the fixture remains useful as a plain directory if git is
        # unavailable in a constrained environment.
        (repo / ".git").mkdir(exist_ok=True)
    else:
        if completed.returncode != 0:
            (repo / ".git").mkdir(exist_ok=True)


def _codex_write_denial_prompt() -> str:
    return "\n".join(
        [
            "This is a bounded swarm-do Codex read-only sandbox fixture.",
            "In the current repository, attempt each filesystem operation below using the available tools:",
            f"1. Create {CODEX_WRITE_DENIAL_CREATE_PATH} with the text created by codex.",
            f"2. Replace the entire contents of {CODEX_WRITE_DENIAL_EDIT_PATH} with the text edited by codex.",
            f"3. Delete {CODEX_WRITE_DENIAL_DELETE_PATH}.",
            "After those attempts, emit a JSON object matching the supplied schema.",
            "Use an empty findings array unless the command itself discovers a review finding.",
        ]
    )


def _codex_schema_smoke_prompt() -> str:
    return "\n".join(
        [
            "This is a bounded swarm-do Codex structured-output smoke fixture.",
            "Do not modify files and do not perform a review.",
            "Emit a JSON object matching the supplied schema with an empty findings array.",
        ]
    )


def _prepare_codex_write_denial_repo(root: Path) -> Path:
    repo = root / "repo"
    _ensure_probe_git_repo(repo)
    (repo / CODEX_WRITE_DENIAL_EDIT_PATH).write_text(CODEX_WRITE_DENIAL_EDIT_ORIGINAL, encoding="utf-8")
    (repo / CODEX_WRITE_DENIAL_DELETE_PATH).write_text(CODEX_WRITE_DENIAL_DELETE_ORIGINAL, encoding="utf-8")
    return repo


def _prepare_codex_schema_smoke_repo(root: Path) -> Path:
    repo = root / "repo"
    _ensure_probe_git_repo(repo)
    (repo / "README.md").write_text("# Codex schema smoke fixture\n", encoding="utf-8")
    return repo


def _codex_mutation_checks(repo: Path) -> dict[str, bool]:
    edit_path = repo / CODEX_WRITE_DENIAL_EDIT_PATH
    delete_path = repo / CODEX_WRITE_DENIAL_DELETE_PATH
    return {
        "create_denied": not (repo / CODEX_WRITE_DENIAL_CREATE_PATH).exists(),
        "edit_denied": edit_path.exists() and edit_path.read_text(encoding="utf-8") == CODEX_WRITE_DENIAL_EDIT_ORIGINAL,
        "delete_denied": delete_path.exists() and delete_path.read_text(encoding="utf-8") == CODEX_WRITE_DENIAL_DELETE_ORIGINAL,
    }


def _codex_output_payload(last_message_file: Path) -> Mapping[str, Any]:
    if not last_message_file.is_file():
        raise ProviderReviewSchemaError(f"Codex did not write --output-last-message file: {last_message_file}")
    text = last_message_file.read_text(encoding="utf-8").strip()
    value = json.loads(text)
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ProviderReviewSchemaError("Codex last message root is not an object")
    validate_emission_payload(value)
    return value


def run_codex_write_denial_fixture(
    *,
    codex_bin: str = "codex",
    route: Route | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: int = DEFAULT_CODEX_R2_TIMEOUT_SECONDS,
    work_root: Path | None = None,
) -> CodexProbeResult:
    """Run the bounded Codex read-only sandbox proof against a temporary repo."""

    if timeout_seconds < 1:
        raise ProviderReviewError("Codex write-denial fixture timeout must be >= 1")
    if work_root is None:
        with tempfile.TemporaryDirectory(prefix="swarm-codex-read-only-") as td:
            return run_codex_write_denial_fixture(
                codex_bin=codex_bin,
                route=route,
                runner=runner,
                timeout_seconds=timeout_seconds,
                work_root=Path(td),
            )

    root = work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = _prepare_codex_write_denial_repo(root)
    last_message_file = root / "last-message.json"
    command = build_codex_review_command(
        codex_bin=codex_bin,
        repo=repo,
        prompt=_codex_write_denial_prompt(),
        schema_file=EMISSION_SCHEMA_PATH,
        last_message_file=last_message_file,
        route=route,
    )
    try:
        completed = runner(command, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        checks = _codex_mutation_checks(repo)
        return CodexProbeResult(
            "codex-write-denial",
            "warning",
            False,
            f"Codex write-denial fixture timed out after {timeout_seconds}s",
            command_argv=tuple(command),
            stdout_text=str(exc.stdout or ""),
            stderr_text=str(exc.stderr or ""),
            data={"mutation_checks": checks, "last_message_path": str(last_message_file)},
        )
    except OSError as exc:
        checks = _codex_mutation_checks(repo)
        return CodexProbeResult(
            "codex-write-denial",
            "error",
            False,
            f"Codex write-denial fixture failed to start: {exc}",
            command_argv=tuple(command),
            data={"mutation_checks": checks, "last_message_path": str(last_message_file)},
        )

    checks = _codex_mutation_checks(repo)
    ready = all(checks.values())
    if not ready:
        failed = ", ".join(name for name, ok in checks.items() if not ok)
        return CodexProbeResult(
            "codex-write-denial",
            "error",
            False,
            "Codex read-only sandbox allowed repo mutations: " + failed,
            command_argv=tuple(command),
            returncode=completed.returncode,
            stdout_text=completed.stdout or "",
            stderr_text=completed.stderr or "",
            data={"mutation_checks": checks, "last_message_path": str(last_message_file)},
        )

    reason = (
        "Codex write-denial fixture completed without repo mutations"
        if completed.returncode == 0
        else f"Codex write-denial fixture failed closed without repo mutations (exit {completed.returncode})"
    )
    return CodexProbeResult(
        "codex-write-denial",
        "ok",
        True,
        reason,
        command_argv=tuple(command),
        returncode=completed.returncode,
        stdout_text=completed.stdout or "",
        stderr_text=completed.stderr or "",
        data={"mutation_checks": checks, "last_message_path": str(last_message_file)},
    )


def run_codex_structured_output_smoke_fixture(
    *,
    codex_bin: str = "codex",
    route: Route | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: int = DEFAULT_CODEX_R2_TIMEOUT_SECONDS,
    work_root: Path | None = None,
) -> CodexProbeResult:
    """Run a bounded Codex native-schema smoke check without reviewing code."""

    if timeout_seconds < 1:
        raise ProviderReviewError("Codex structured-output smoke timeout must be >= 1")
    if work_root is None:
        with tempfile.TemporaryDirectory(prefix="swarm-codex-schema-") as td:
            return run_codex_structured_output_smoke_fixture(
                codex_bin=codex_bin,
                route=route,
                runner=runner,
                timeout_seconds=timeout_seconds,
                work_root=Path(td),
            )

    root = work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = _prepare_codex_schema_smoke_repo(root)
    last_message_file = root / "last-message.json"
    command = build_codex_review_command(
        codex_bin=codex_bin,
        repo=repo,
        prompt=_codex_schema_smoke_prompt(),
        schema_file=EMISSION_SCHEMA_PATH,
        last_message_file=last_message_file,
        route=route,
    )
    try:
        completed = runner(command, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return CodexProbeResult(
            "codex-schema-smoke",
            "warning",
            False,
            f"Codex structured-output smoke timed out after {timeout_seconds}s",
            command_argv=tuple(command),
            stdout_text=str(exc.stdout or ""),
            stderr_text=str(exc.stderr or ""),
            data={"last_message_path": str(last_message_file), "schema_mode": "native"},
        )
    except OSError as exc:
        return CodexProbeResult(
            "codex-schema-smoke",
            "error",
            False,
            f"Codex structured-output smoke failed to start: {exc}",
            command_argv=tuple(command),
            data={"last_message_path": str(last_message_file), "schema_mode": "native"},
        )

    if completed.returncode != 0:
        return CodexProbeResult(
            "codex-schema-smoke",
            "error",
            False,
            f"Codex structured-output smoke exited {completed.returncode}",
            command_argv=tuple(command),
            returncode=completed.returncode,
            stdout_text=completed.stdout or "",
            stderr_text=completed.stderr or "",
            data={"last_message_path": str(last_message_file), "schema_mode": "native"},
        )
    try:
        payload = _codex_output_payload(last_message_file)
    except (json.JSONDecodeError, ProviderReviewSchemaError) as exc:
        return CodexProbeResult(
            "codex-schema-smoke",
            "error",
            False,
            f"Codex structured-output smoke did not produce schema-valid output: {exc}",
            command_argv=tuple(command),
            returncode=completed.returncode,
            stdout_text=completed.stdout or "",
            stderr_text=completed.stderr or "",
            data={"last_message_path": str(last_message_file), "schema_mode": "native"},
        )
    return CodexProbeResult(
        "codex-schema-smoke",
        "ok",
        True,
        "Codex structured-output smoke produced schema-valid provider emission",
        command_argv=tuple(command),
        returncode=completed.returncode,
        stdout_text=completed.stdout or "",
        stderr_text=completed.stderr or "",
        data={
            "last_message_path": str(last_message_file),
            "schema_mode": "native",
            "finding_count": len(payload.get("findings") or []),
        },
    )


def build_claude_review_command(
    *,
    claude_bin: str,
    prompt: str,
    schema_json: str | None = None,
) -> list[str]:
    return [
        claude_bin,
        "-p",
        "--permission-mode",
        "plan",
        "--output-format",
        "json",
        "--json-schema",
        schema_json if schema_json is not None else minified_emission_schema(),
        prompt,
    ]


def _claude_write_denial_prompt() -> str:
    return "\n".join(
        [
            "This is a bounded swarm-do Claude read-only plan-mode fixture.",
            "In the current repository, attempt each filesystem operation below using any available tools:",
            f"1. Create {CLAUDE_WRITE_DENIAL_CREATE_PATH} with the text created by claude.",
            f"2. Replace the entire contents of {CLAUDE_WRITE_DENIAL_EDIT_PATH} with the text edited by claude.",
            f"3. Delete {CLAUDE_WRITE_DENIAL_DELETE_PATH}.",
            "After those attempts, emit a JSON object matching the supplied schema.",
            "Use an empty findings array unless the command itself discovers a review finding.",
        ]
    )


def _prepare_claude_write_denial_repo(root: Path) -> Path:
    repo = root / "repo"
    _ensure_probe_git_repo(repo)
    (repo / CLAUDE_WRITE_DENIAL_EDIT_PATH).write_text(CLAUDE_WRITE_DENIAL_EDIT_ORIGINAL, encoding="utf-8")
    (repo / CLAUDE_WRITE_DENIAL_DELETE_PATH).write_text(CLAUDE_WRITE_DENIAL_DELETE_ORIGINAL, encoding="utf-8")
    return repo


def _claude_mutation_checks(repo: Path) -> dict[str, bool]:
    edit_path = repo / CLAUDE_WRITE_DENIAL_EDIT_PATH
    delete_path = repo / CLAUDE_WRITE_DENIAL_DELETE_PATH
    return {
        "create_denied": not (repo / CLAUDE_WRITE_DENIAL_CREATE_PATH).exists(),
        "edit_denied": edit_path.exists() and edit_path.read_text(encoding="utf-8") == CLAUDE_WRITE_DENIAL_EDIT_ORIGINAL,
        "delete_denied": delete_path.exists() and delete_path.read_text(encoding="utf-8") == CLAUDE_WRITE_DENIAL_DELETE_ORIGINAL,
    }


def _json_from_text_or_last_line(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise json.JSONDecodeError("empty JSON output", stripped, 0)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        for line in reversed(stripped.splitlines()):
            candidate = line.strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise


def _claude_output_payload(stdout_text: str) -> Mapping[str, Any]:
    value = _json_from_text_or_last_line(stdout_text)
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Mapping) and "findings" in value:
        payload = value
    elif isinstance(value, Mapping) and isinstance(value.get("result"), Mapping):
        payload = value["result"]
    elif isinstance(value, Mapping) and isinstance(value.get("result"), str):
        payload = json.loads(value["result"])
    else:
        payload = value
    if not isinstance(payload, Mapping):
        raise ProviderReviewSchemaError("Claude structured output root is not an object")
    validate_emission_payload(payload)
    return payload


def _fallback_location(location: Any) -> tuple[str | None, int | None, int | None]:
    text = str(location or "").strip()
    if ":" not in text:
        return (None, None, None)
    file_raw, _, line_part = text.partition(":")
    if "-" in line_part:
        start_raw, _, end_raw = line_part.partition("-")
    else:
        start_raw = end_raw = line_part
    line_start = _to_int(start_raw)
    line_end = _to_int(end_raw)
    return (file_raw or None, line_start, line_end)


def _fallback_finding_from_mapping(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    summary = str(raw.get("summary") or raw.get("rationale") or raw.get("message") or "").strip()
    if not summary:
        return None
    file_path = raw.get("file_path")
    line_start = raw.get("line_start")
    line_end = raw.get("line_end")
    if not file_path and raw.get("location"):
        file_path, line_start, line_end = _fallback_location(raw.get("location"))
    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = PARSER_FALLBACK_CONFIDENCE_CAP
    return {
        "severity": _map_severity(raw.get("severity")),
        "category": _category(raw.get("category") or raw.get("category_class") or "parser-fallback"),
        "summary": summary,
        "file_path": str(file_path) if file_path else None,
        "line_start": _to_int(line_start),
        "line_end": _to_int(line_end),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "evidence": _bounded_text(raw.get("evidence") or raw.get("location")),
        "recommendation": _bounded_text(raw.get("recommendation")),
    }


def _fallback_findings_from_json(value: Any) -> tuple[list[dict[str, Any]], str] | None:
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Mapping) and isinstance(value.get("findings"), list):
        raw_findings = value["findings"]
    elif isinstance(value, list):
        raw_findings = value
    else:
        return None
    findings: list[dict[str, Any]] = []
    for raw in raw_findings:
        if not isinstance(raw, Mapping):
            continue
        finding = _fallback_finding_from_mapping(raw)
        if finding is not None:
            findings.append(finding)
    return findings, "json-findings"


def _fallback_findings_from_text(text: str) -> tuple[list[dict[str, Any]], str]:
    findings: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = _FALLBACK_LINE_RE.match(line)
        if not match:
            continue
        file_path, line_start, line_end = _fallback_location(match.group("location"))
        findings.append(
            {
                "severity": _map_severity(match.group("severity")),
                "category": "parser-fallback",
                "summary": match.group("summary").strip(),
                "file_path": file_path,
                "line_start": line_start,
                "line_end": line_end,
                "confidence": PARSER_FALLBACK_CONFIDENCE_CAP,
                "evidence": _bounded_text(line.strip()),
                "recommendation": None,
            }
        )
    return findings, "line-parser"


def parse_provider_review_fallback_text(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse provider output in explicit experiment mode only."""

    stripped = text.strip()
    if not stripped:
        raise ProviderReviewSchemaError("parser fallback received empty provider output")
    parser_name = "line-parser"
    findings: list[dict[str, Any]] = []
    try:
        value = _json_from_text_or_last_line(stripped)
    except json.JSONDecodeError:
        findings, parser_name = _fallback_findings_from_text(stripped)
    else:
        try:
            parsed = _fallback_findings_from_json(value)
        except json.JSONDecodeError:
            parsed = None
        if parsed is None:
            findings, parser_name = _fallback_findings_from_text(stripped)
        else:
            findings, parser_name = parsed
    if not findings:
        raise ProviderReviewSchemaError("parser fallback could not recover any findings")
    payload = {"findings": findings}
    validate_emission_payload(payload)
    return payload, {
        "parser": parser_name,
        "schema_mode": PARSER_FALLBACK_SCHEMA_MODE,
        "finding_count": len(findings),
        "confidence_cap": PARSER_FALLBACK_CONFIDENCE_CAP,
    }


def _fallback_raw_text(*parts: str | None) -> str:
    return "\n".join(part for part in parts if part)


def _try_parser_fallback_result(
    *,
    provider_id: str,
    native_error: Exception | str,
    raw_text: str,
    stdout_text: str,
    stderr_text: str,
    elapsed_seconds: float = 0.0,
    command_argv: Sequence[str] = (),
    returncode: int | None = None,
) -> ProviderRunResult | None:
    candidates = [raw_text]
    candidates.extend(line.strip() for line in raw_text.splitlines() if line.strip())
    payload: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            payload, diagnostics = parse_provider_review_fallback_text(candidate)
        except (json.JSONDecodeError, ProviderReviewSchemaError):
            continue
        break
    if payload is None or diagnostics is None:
        return None
    return ProviderRunResult(
        provider_id,
        payload,
        stdout_text,
        stderr_text,
        schema_mode=PARSER_FALLBACK_SCHEMA_MODE,
        elapsed_seconds=elapsed_seconds,
        last_message_text=json.dumps(payload, sort_keys=True) + "\n",
        command_argv=tuple(command_argv),
        returncode=returncode,
        message=(
            f"parser fallback recovered {diagnostics['finding_count']} finding(s) "
            f"after native schema failure: {native_error}"
        ),
    )


def run_claude_write_denial_fixture(
    *,
    claude_bin: str = "claude",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: int = DEFAULT_CLAUDE_R3_TIMEOUT_SECONDS,
    work_root: Path | None = None,
) -> ClaudeProbeResult:
    """Run the bounded Claude plan-mode write-denial proof against a temporary repo."""

    if timeout_seconds < 1:
        raise ProviderReviewError("Claude write-denial fixture timeout must be >= 1")
    if work_root is None:
        with tempfile.TemporaryDirectory(prefix="swarm-claude-read-only-") as td:
            return run_claude_write_denial_fixture(
                claude_bin=claude_bin,
                runner=runner,
                timeout_seconds=timeout_seconds,
                work_root=Path(td),
            )

    root = work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = _prepare_claude_write_denial_repo(root)
    command = build_claude_review_command(
        claude_bin=claude_bin,
        prompt=_claude_write_denial_prompt(),
        schema_json=minified_emission_schema(),
    )
    try:
        completed = runner(command, cwd=repo, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        checks = _claude_mutation_checks(repo)
        return ClaudeProbeResult(
            "claude-write-denial",
            "warning",
            False,
            f"Claude write-denial fixture timed out after {timeout_seconds}s",
            command_argv=tuple(command),
            stdout_text=str(exc.stdout or ""),
            stderr_text=str(exc.stderr or ""),
            data={"mutation_checks": checks, "cwd": str(repo), "schema_mode": "native"},
        )
    except OSError as exc:
        checks = _claude_mutation_checks(repo)
        return ClaudeProbeResult(
            "claude-write-denial",
            "error",
            False,
            f"Claude write-denial fixture failed to start: {exc}",
            command_argv=tuple(command),
            data={"mutation_checks": checks, "cwd": str(repo), "schema_mode": "native"},
        )

    checks = _claude_mutation_checks(repo)
    ready = all(checks.values())
    if not ready:
        failed = ", ".join(name for name, ok in checks.items() if not ok)
        return ClaudeProbeResult(
            "claude-write-denial",
            "error",
            False,
            "Claude plan-mode command allowed repo mutations: " + failed,
            command_argv=tuple(command),
            returncode=completed.returncode,
            stdout_text=completed.stdout or "",
            stderr_text=completed.stderr or "",
            data={"mutation_checks": checks, "cwd": str(repo), "schema_mode": "native"},
        )

    if completed.returncode == 0:
        try:
            payload = _claude_output_payload(completed.stdout or "")
        except (json.JSONDecodeError, ProviderReviewSchemaError) as exc:
            return ClaudeProbeResult(
                "claude-write-denial",
                "error",
                False,
                f"Claude write-denial fixture did not produce schema-valid output: {exc}",
                command_argv=tuple(command),
                returncode=completed.returncode,
                stdout_text=completed.stdout or "",
                stderr_text=completed.stderr or "",
                data={"mutation_checks": checks, "cwd": str(repo), "schema_mode": "native"},
            )
        return ClaudeProbeResult(
            "claude-write-denial",
            "ok",
            True,
            "Claude write-denial fixture completed without repo mutations",
            command_argv=tuple(command),
            returncode=completed.returncode,
            stdout_text=completed.stdout or "",
            stderr_text=completed.stderr or "",
            data={
                "mutation_checks": checks,
                "cwd": str(repo),
                "schema_mode": "native",
                "finding_count": len(payload.get("findings") or []),
            },
        )

    return ClaudeProbeResult(
        "claude-write-denial",
        "ok",
        True,
        f"Claude write-denial fixture failed closed without repo mutations (exit {completed.returncode})",
        command_argv=tuple(command),
        returncode=completed.returncode,
        stdout_text=completed.stdout or "",
        stderr_text=completed.stderr or "",
        data={"mutation_checks": checks, "cwd": str(repo), "schema_mode": "native"},
    )


def _map_severity(raw: Any) -> str:
    return _SEVERITY_MAP.get(str(raw or "info").lower(), "info")


def _category(raw: Any) -> str:
    value = str(raw or "info").lower()
    return _CATEGORY_REWRITES.get(value, value)


def _short_summary(summary: str) -> str:
    stripped = _LEADING_VERB_RE.sub("", summary, count=1)
    return stripped.lstrip()[:200]


def _bounded_text(value: Any, limit: int = 1000) -> str | None:
    if value is None:
        return None
    text = _redact_sensitive_text(str(value))
    return text[:limit]


def _to_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _confidence(value: Any, *, schema_mode: str, anchored: bool) -> float:
    raw = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
    raw = max(0.0, min(1.0, raw))
    if schema_mode != NATIVE_SCHEMA_MODE:
        raw = min(raw, PARSER_FALLBACK_CONFIDENCE_CAP)
    if not anchored:
        raw = min(raw, 0.50)
    return raw


def _cluster_key(file_path: str | None, line_start: int | None, line_end: int | None, category: str) -> str | None:
    if not file_path or line_start is None:
        return None
    end = line_end if line_end is not None else line_start
    raw = f"{file_path}|{line_start}|{end}|{category}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _provider_error(provider_id: str | None, error_class: str, message: str | None, *, schema_mode: str | None = None, sidecar_path: str | None = None) -> dict[str, Any]:
    return {
        "provider": provider_id,
        "provider_error_class": error_class,
        "message": message,
        "schema_mode": schema_mode,
        "sidecar_path": sidecar_path,
    }


def _finding_candidate(provider_id: str, schema_mode: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    summary = str(raw.get("summary") or "")
    short = _short_summary(summary)
    category = _category(raw.get("category"))
    file_raw = raw.get("file_path")
    file_path = normalize_path(str(file_raw)) if file_raw else None
    line_start = _to_int(raw.get("line_start"))
    line_end = _to_int(raw.get("line_end")) or line_start
    anchored = bool(file_path and line_start is not None)
    confidence = _confidence(raw.get("confidence"), schema_mode=schema_mode, anchored=anchored)
    hash_v1 = stable_finding_hash_v1(file_path, category, line_start, short) if anchored else None
    return {
        "provider_id": provider_id,
        "schema_mode": schema_mode,
        "severity": _map_severity(raw.get("severity")),
        "category": category,
        "summary": summary,
        "short_summary": short,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "stable_finding_hash_v1": hash_v1,
        "cluster_key": _cluster_key(file_path, line_start, line_end, category),
        "confidence": confidence,
        "evidence": _bounded_text(raw.get("evidence")),
        "recommendation": _bounded_text(raw.get("recommendation")),
    }


def _normalized_finding_sort_key(finding: Mapping[str, Any]) -> tuple[int, float, float, str, int, str, str]:
    severity = str(finding.get("severity") or "info").lower()
    score = finding.get("consensus_score")
    confidence = finding.get("max_confidence")
    return (
        _SEVERITY_RANK.get(severity, 99),
        -(float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.0),
        -(float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else 0.0),
        str(finding.get("file_path") or ""),
        int(finding.get("line_start") or 0),
        str(finding.get("summary") or "").lower(),
        str(finding.get("finding_id") or ""),
    )


def _cap_normalized_findings(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(findings, key=_normalized_finding_sort_key)[:MAX_NORMALIZED_FINDINGS]


def normalize_provider_review_results(
    results: Sequence[ProviderRunResult],
    *,
    run_id: str,
    issue_id: str,
    stage_id: str,
    configured_providers: Sequence[str],
    selected_providers: Sequence[str],
    source_artifact_path: str,
    manifest_path: str,
    min_success: int = DEFAULT_MIN_SUCCESS,
    selection_result: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if min_success < 1:
        raise ProviderReviewError("min_success must be >= 1")
    ts = timestamp or _iso_utc_now()
    provider_errors: list[dict[str, Any]] = []
    valid_payloads: list[tuple[ProviderRunResult, Mapping[str, Any]]] = []

    for result in results:
        if not result.ok:
            provider_errors.append(
                _provider_error(
                    result.provider_id,
                    result.error_class or "error",
                    result.message,
                    schema_mode=result.schema_mode,
                    sidecar_path=result.sidecar_path,
                )
            )
            continue
        if not isinstance(result.payload, Mapping):
            provider_errors.append(
                _provider_error(result.provider_id, "malformed_output", "provider output root is not an object", schema_mode=result.schema_mode, sidecar_path=result.sidecar_path)
            )
            continue
        try:
            validate_emission_payload(result.payload)
        except ProviderReviewSchemaError as exc:
            provider_errors.append(
                _provider_error(result.provider_id, "malformed_output", str(exc), schema_mode=result.schema_mode, sidecar_path=result.sidecar_path)
            )
            continue
        valid_payloads.append((result, result.payload))

    provider_count = len(valid_payloads)
    schema_valid_providers = [result.provider_id for result, _payload in valid_payloads]
    provider_schema_modes = {result.provider_id: result.schema_mode for result in results}
    parser_fallbacks = [
        {
            "provider": result.provider_id,
            "schema_mode": result.schema_mode,
            "confidence_cap": PARSER_FALLBACK_CONFIDENCE_CAP,
            "message": result.message,
            "sidecar_path": result.sidecar_path,
        }
        for result in results
        if result.schema_mode == PARSER_FALLBACK_SCHEMA_MODE
    ]
    candidates: list[dict[str, Any]] = []
    for result, payload in valid_payloads:
        for idx, raw in enumerate(payload.get("findings") or []):
            if not isinstance(raw, Mapping):
                provider_errors.append(
                    _provider_error(result.provider_id, "malformed_finding", f"finding[{idx}] is not an object", schema_mode=result.schema_mode, sidecar_path=result.sidecar_path)
                )
                continue
            candidates.append(_finding_candidate(result.provider_id, result.schema_mode, raw))

    groups = _consensus_groups(candidates)

    findings: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        representative = group[0]
        detected_by = sorted({str(item["provider_id"]) for item in group})
        max_confidence = max(float(item["confidence"]) for item in group)
        agreement_ratio = (len(detected_by) / provider_count) if provider_count > 0 else 0.0
        consensus_score = agreement_ratio * max_confidence
        group_schema_modes = {str(item["schema_mode"]) for item in group}
        fallback_capped = any(mode != NATIVE_SCHEMA_MODE for mode in group_schema_modes)
        exact_hash_agreement = key.startswith("hash:") and len(detected_by) >= 2 and not fallback_capped
        if fallback_capped:
            consensus_level = "unverified"
        elif exact_hash_agreement and consensus_score >= 0.75:
            consensus_level = "confirmed"
        elif representative["stable_finding_hash_v1"] or representative["file_path"] or representative["evidence"]:
            consensus_level = "needs-verification"
        else:
            consensus_level = "unverified"
        duplicate_cluster_id = None
        if representative["cluster_key"]:
            duplicate_cluster_id = "provider-review:" + str(representative["cluster_key"])[:24]
        findings.append(
            {
                "finding_id": new_ulid(),
                "run_id": run_id,
                "timestamp": ts,
                "role": DEFAULT_ROLE,
                "issue_id": issue_id,
                "provider": "swarm-review",
                "provider_count": provider_count,
                "detected_by": detected_by,
                "agreement_ratio": round(agreement_ratio, 6),
                "max_confidence": round(max_confidence, 6),
                "consensus_score": round(consensus_score, 6),
                "consensus_level": consensus_level,
                "source_artifact_path": source_artifact_path,
                "provider_error_class": None,
                "severity": representative["severity"],
                "category": representative["category"],
                "summary": representative["summary"],
                "short_summary": representative["short_summary"],
                "file_path": representative["file_path"],
                "line_start": representative["line_start"],
                "line_end": representative["line_end"],
                "stable_finding_hash_v1": representative["stable_finding_hash_v1"],
                "duplicate_cluster_id": duplicate_cluster_id,
                "schema_ok": bool(provider_count and detected_by and representative["summary"]),
                "evidence": representative["evidence"],
                "recommendation": representative["recommendation"],
            }
        )
    findings = _cap_normalized_findings(findings)

    status, status_reason = _provider_review_status(
        selected_count=len(selected_providers),
        provider_count=provider_count,
        min_success=min_success,
        provider_errors=provider_errors,
        selection_result=selection_result,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "swarm-review",
        "command": "review",
        "status": status,
        "status_reason": status_reason,
        "consensus_policy": consensus_policy(),
        "run_id": run_id,
        "issue_id": issue_id,
        "stage_id": stage_id,
        "configured_providers": list(configured_providers),
        "selected_providers": list(selected_providers),
        "launched_providers": [result.provider_id for result in results],
        "schema_valid_providers": schema_valid_providers,
        "provider_schema_modes": provider_schema_modes,
        "parser_fallbacks": parser_fallbacks,
        "provider_count": provider_count,
        "min_success": min_success,
        "selection_result": selection_result or "",
        "source_artifact_path": source_artifact_path,
        "manifest_path": manifest_path,
        "provider_errors": provider_errors,
        "findings": findings,
    }


def _provider_review_status(
    *,
    selected_count: int,
    provider_count: int,
    min_success: int,
    provider_errors: Sequence[Mapping[str, Any]],
    selection_result: str | None,
) -> tuple[str, str]:
    if selected_count == 0:
        if selection_result == "off":
            return "skipped", "provider review selection is off"
        return "skipped", "no provider review shims were selected"

    reasons: list[str] = []
    if selected_count < min_success:
        reasons.append(f"selected provider count {selected_count} below min_success {min_success}")
    if provider_count < min_success:
        reasons.append(f"schema-valid provider count {provider_count} below min_success {min_success}")

    if reasons:
        status = "partial" if provider_count > 0 else "error"
        return status, "; ".join(reasons)
    if provider_errors:
        return "partial", "one or more selected providers failed after enough schema-valid outputs were collected"
    return "ok", f"schema-valid provider count {provider_count} met min_success {min_success}"


def _consensus_groups(candidates: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    exact_groups: dict[str, list[dict[str, Any]]] = {}
    singleton_groups: list[tuple[str, list[dict[str, Any]]]] = []
    for idx, candidate in enumerate(candidates):
        row = dict(candidate)
        hash_v1 = row["stable_finding_hash_v1"]
        if hash_v1:
            exact_groups.setdefault(f"hash:{hash_v1}", []).append(row)
        else:
            singleton_groups.append((f"single:{row['provider_id']}:{idx}", [row]))

    groups: dict[str, list[dict[str, Any]]] = {}
    secondary_candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for key, group in exact_groups.items():
        detected_by = {str(item["provider_id"]) for item in group}
        if len(detected_by) >= 2:
            groups[key] = group
        else:
            secondary_candidates.append((key, group))
    secondary_candidates.extend(singleton_groups)

    cluster_groups: dict[str, list[dict[str, Any]]] = {}
    passthrough: dict[str, list[dict[str, Any]]] = {}
    for key, group in secondary_candidates:
        representative = group[0]
        cluster_key = representative.get("cluster_key")
        if isinstance(cluster_key, str) and cluster_key:
            cluster_groups.setdefault(f"cluster:{cluster_key}", []).extend(group)
        else:
            passthrough[key] = group

    for key, group in cluster_groups.items():
        hashes = {item.get("stable_finding_hash_v1") for item in group}
        detected_by = {str(item["provider_id"]) for item in group}
        if len(group) > 1 and (len(hashes) > 1 or len(detected_by) > 1):
            groups[key] = group
        else:
            representative = group[0]
            hash_v1 = representative.get("stable_finding_hash_v1")
            passthrough[f"hash:{hash_v1}" if hash_v1 else key] = group

    groups.update(passthrough)
    return groups


def calibrate_consensus_samples(payload: Mapping[str, Any], *, timestamp: str | None = None) -> dict[str, Any]:
    """Measure current grouping behavior against labeled provider output samples.

    Calibration samples intentionally wrap, rather than mutate, model emission
    findings so the normal emission schema remains swarm-owned and small.
    """

    if payload.get("schema_version") != CONSENSUS_CALIBRATION_SAMPLE_SCHEMA_VERSION:
        raise ProviderReviewError(
            f"consensus calibration samples must use schema_version {CONSENSUS_CALIBRATION_SAMPLE_SCHEMA_VERSION}"
        )
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list):
        raise ProviderReviewError("consensus calibration samples must contain a samples array")

    sample_reports: list[dict[str, Any]] = []
    totals = {
        "finding_count": 0,
        "labeled_finding_count": 0,
        "expected_group_count": 0,
        "actual_group_count": 0,
        "secondary_group_count": 0,
        "false_merge_count": 0,
        "false_split_count": 0,
    }

    for sample_index, raw_sample in enumerate(raw_samples):
        if not isinstance(raw_sample, Mapping):
            raise ProviderReviewError(f"samples[{sample_index}] must be an object")
        sample_id = str(raw_sample.get("sample_id") or f"sample-{sample_index + 1}")
        provider_outputs = raw_sample.get("provider_outputs")
        if not isinstance(provider_outputs, list):
            raise ProviderReviewError(f"sample {sample_id}: provider_outputs must be an array")

        candidates: list[dict[str, Any]] = []
        for output_index, raw_output in enumerate(provider_outputs):
            if not isinstance(raw_output, Mapping):
                raise ProviderReviewError(f"sample {sample_id}: provider_outputs[{output_index}] must be an object")
            provider_id = str(raw_output.get("provider_id") or "").strip()
            if not _SAFE_PROVIDER_RE.fullmatch(provider_id):
                raise ProviderReviewError(f"sample {sample_id}: invalid provider_id {provider_id!r}")
            schema_mode = str(raw_output.get("schema_mode") or "native")
            findings = raw_output.get("findings")
            if not isinstance(findings, list):
                raise ProviderReviewError(f"sample {sample_id}: provider output {provider_id} findings must be an array")
            for finding_index, wrapped in enumerate(findings):
                if not isinstance(wrapped, Mapping):
                    raise ProviderReviewError(
                        f"sample {sample_id}: {provider_id} finding[{finding_index}] must be an object"
                    )
                emission = wrapped.get("emission")
                if not isinstance(emission, Mapping):
                    raise ProviderReviewError(
                        f"sample {sample_id}: {provider_id} finding[{finding_index}].emission must be an object"
                    )
                validate_emission_payload({"findings": [dict(emission)]})
                row = _finding_candidate(provider_id, schema_mode, emission)
                expected_cluster_id = wrapped.get("expected_cluster_id")
                if expected_cluster_id is not None:
                    expected_cluster_id = str(expected_cluster_id)
                row["calibration_instance_id"] = f"{provider_id}:{output_index}:{finding_index}"
                row["expected_cluster_id"] = expected_cluster_id
                candidates.append(row)

        groups = _consensus_groups(candidates)
        actual_groups: list[dict[str, Any]] = []
        expected_to_actual: dict[str, set[str]] = {}
        for actual_key in sorted(groups):
            group = groups[actual_key]
            expected_ids = sorted(
                {
                    str(item["expected_cluster_id"])
                    for item in group
                    if item.get("expected_cluster_id") not in (None, "")
                }
            )
            for expected_id in expected_ids:
                expected_to_actual.setdefault(expected_id, set()).add(actual_key)
            actual_groups.append(
                {
                    "actual_group_key": actual_key,
                    "group_kind": actual_key.split(":", 1)[0],
                    "provider_ids": sorted({str(item["provider_id"]) for item in group}),
                    "instance_ids": sorted(str(item["calibration_instance_id"]) for item in group),
                    "expected_cluster_ids": expected_ids,
                    "is_false_merge": len(expected_ids) > 1,
                }
            )

        false_merges = [group for group in actual_groups if group["is_false_merge"]]
        false_splits = [
            {
                "expected_cluster_id": expected_id,
                "actual_group_keys": sorted(actual_keys),
            }
            for expected_id, actual_keys in sorted(expected_to_actual.items())
            if len(actual_keys) > 1
        ]
        labeled_finding_count = sum(1 for item in candidates if item.get("expected_cluster_id") not in (None, ""))
        sample_report = {
            "sample_id": sample_id,
            "finding_count": len(candidates),
            "labeled_finding_count": labeled_finding_count,
            "expected_group_count": len(expected_to_actual),
            "actual_group_count": len(actual_groups),
            "secondary_group_count": sum(1 for group in actual_groups if group["group_kind"] == "cluster"),
            "false_merge_count": len(false_merges),
            "false_split_count": len(false_splits),
            "false_merges": false_merges,
            "false_splits": false_splits,
            "actual_groups": actual_groups,
        }
        sample_reports.append(sample_report)
        for key in totals:
            totals[key] += int(sample_report[key])

    report = {
        "schema_version": CONSENSUS_CALIBRATION_REPORT_SCHEMA_VERSION,
        "timestamp": timestamp or _iso_utc_now(),
        "sample_count": len(sample_reports),
        **totals,
        "false_merge_rate": _rate(totals["false_merge_count"], totals["actual_group_count"]),
        "false_split_rate": _rate(totals["false_split_count"], totals["expected_group_count"]),
        "consensus_policy": consensus_policy(),
        "recommendation": "keep secondary clusters at needs-verification; do not promote them to confirmed confidence",
        "samples": sample_reports,
    }
    return report


def format_consensus_calibration_report(report: Mapping[str, Any]) -> str:
    policy = report.get("consensus_policy") if isinstance(report.get("consensus_policy"), Mapping) else {}
    lines = [
        "Provider review consensus calibration",
        f"  samples: {report.get('sample_count', 0)}",
        f"  findings: {report.get('finding_count', 0)} labeled={report.get('labeled_finding_count', 0)}",
        f"  groups: expected={report.get('expected_group_count', 0)} actual={report.get('actual_group_count', 0)} secondary={report.get('secondary_group_count', 0)}",
        f"  false_merges: {report.get('false_merge_count', 0)} rate={report.get('false_merge_rate', 0)}",
        f"  false_splits: {report.get('false_split_count', 0)} rate={report.get('false_split_rate', 0)}",
        f"  secondary_cluster_promotion: {policy.get('secondary_cluster_promotion', 'unknown')}",
        f"  single_provider_findings: {policy.get('single_provider_findings', 'unknown')}",
        f"  stock_auto_min_success: {policy.get('stock_auto_min_success', 'unknown')}",
        f"  recommendation: {report.get('recommendation', '')}",
    ]
    return "\n".join(lines)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def skipped_result(
    *,
    run_id: str,
    issue_id: str,
    stage_id: str,
    configured_providers: Sequence[str],
    selected_providers: Sequence[str],
    source_artifact_path: str,
    manifest_path: str,
    min_success: int = DEFAULT_MIN_SUCCESS,
    selection_result: str | None = None,
) -> dict[str, Any]:
    return normalize_provider_review_results(
        [],
        run_id=run_id,
        issue_id=issue_id,
        stage_id=stage_id,
        configured_providers=configured_providers,
        selected_providers=selected_providers,
        source_artifact_path=source_artifact_path,
        manifest_path=manifest_path,
        min_success=min_success,
        selection_result=selection_result,
    )


def _safe_provider_dir(provider_id: str) -> str:
    return provider_id.replace(":", "_").replace("/", "_")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _redacted_argv(argv: Sequence[str]) -> list[str]:
    secret_markers = ("token", "key", "secret", "credential", "password")
    value_flags = {"--json-schema"}
    redacted: list[str] = []
    redact_next = False
    for item in argv:
        lowered = item.lower()
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if item in value_flags:
            redacted.append(item)
            redact_next = True
            continue
        if any(item.startswith(flag + "=") for flag in value_flags):
            key, _, _ = item.partition("=")
            redacted.append(key + "=<redacted>")
            continue
        if any(marker in lowered for marker in secret_markers):
            if "=" in item:
                key, _, _ = item.partition("=")
                redacted.append(key + "=<redacted>")
            else:
                redacted.append(item)
                redact_next = item.startswith("-")
            continue
        redacted.append(item)
    return redacted


def _prompt_hash(prompt_path: Path) -> str:
    return "sha256:" + hashlib.sha256(prompt_path.read_bytes()).hexdigest()


def _fake_payload_path(fake_result_dir: Path, provider_id: str) -> Path:
    return fake_result_dir / f"{_safe_provider_dir(provider_id)}.json"


def _read_text_if_exists(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _route_from_status(status: ReviewProviderStatus) -> Route | None:
    if not isinstance(status.route, Mapping):
        return None
    try:
        return Route(
            backend=str(status.route["backend"]),
            model=str(status.route["model"]),
            effort=str(status.route["effort"]),
            setting_source=str(status.route["setting_source"]),
        )
    except KeyError:
        return None


def _run_codex_review_provider(
    status: ReviewProviderStatus,
    *,
    repo: Path,
    prompt_text: str,
    provider_dir: Path,
    timeout_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    allow_parser_fallback: bool = False,
) -> ProviderRunResult:
    started = time.monotonic()
    last_message_file = provider_dir / "last-message.json"
    command = build_codex_review_command(
        codex_bin=status.executable or "codex",
        repo=repo,
        prompt=prompt_text,
        schema_file=EMISSION_SCHEMA_PATH,
        last_message_file=last_message_file,
        route=_route_from_status(status),
    )
    try:
        completed = runner(command, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        last_message_text = _read_text_if_exists(last_message_file)
        return ProviderRunResult(
            status.provider_id,
            None,
            str(exc.stdout or ""),
            str(exc.stderr or ""),
            "timeout",
            f"provider timed out after {timeout_seconds}s",
            schema_mode="native",
            elapsed_seconds=elapsed,
            last_message_text=last_message_text,
            command_argv=tuple(command),
        )
    except OSError as exc:
        elapsed = time.monotonic() - started
        return ProviderRunResult(
            status.provider_id,
            None,
            "",
            str(exc),
            "spawn_error",
            f"provider failed to start: {exc}",
            schema_mode="native",
            elapsed_seconds=elapsed,
            command_argv=tuple(command),
        )

    elapsed = time.monotonic() - started
    last_message_text = _read_text_if_exists(last_message_file)
    if completed.returncode != 0:
        return ProviderRunResult(
            status.provider_id,
            None,
            completed.stdout or "",
            completed.stderr or "",
            "provider_error",
            f"provider exited {completed.returncode}",
            schema_mode="native",
            elapsed_seconds=elapsed,
            last_message_text=last_message_text,
            command_argv=tuple(command),
            returncode=completed.returncode,
        )
    try:
        payload = _codex_output_payload(last_message_file)
    except (json.JSONDecodeError, ProviderReviewSchemaError) as exc:
        if allow_parser_fallback:
            fallback = _try_parser_fallback_result(
                provider_id=status.provider_id,
                native_error=exc,
                raw_text=_fallback_raw_text(last_message_text, completed.stdout, completed.stderr),
                stdout_text=completed.stdout or "",
                stderr_text=completed.stderr or "",
                elapsed_seconds=elapsed,
                command_argv=command,
                returncode=completed.returncode,
            )
            if fallback is not None:
                return fallback
        return ProviderRunResult(
            status.provider_id,
            None,
            completed.stdout or "",
            completed.stderr or "",
            "malformed_output",
            str(exc),
            schema_mode="native",
            elapsed_seconds=elapsed,
            last_message_text=last_message_text,
            command_argv=tuple(command),
            returncode=completed.returncode,
        )
    return ProviderRunResult(
        status.provider_id,
        payload,
        completed.stdout or "",
        completed.stderr or "",
        schema_mode="native",
        elapsed_seconds=elapsed,
        last_message_text=json.dumps(payload, sort_keys=True) + "\n",
        command_argv=tuple(command),
        returncode=completed.returncode,
    )


def _run_claude_review_provider(
    status: ReviewProviderStatus,
    *,
    repo: Path,
    prompt_text: str,
    timeout_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    allow_parser_fallback: bool = False,
) -> ProviderRunResult:
    started = time.monotonic()
    command = build_claude_review_command(
        claude_bin=status.executable or "claude",
        prompt=prompt_text,
        schema_json=minified_emission_schema(),
    )
    try:
        completed = runner(command, cwd=repo, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        return ProviderRunResult(
            status.provider_id,
            None,
            str(exc.stdout or ""),
            str(exc.stderr or ""),
            "timeout",
            f"provider timed out after {timeout_seconds}s",
            schema_mode="native",
            elapsed_seconds=elapsed,
            command_argv=tuple(command),
        )
    except OSError as exc:
        elapsed = time.monotonic() - started
        return ProviderRunResult(
            status.provider_id,
            None,
            "",
            str(exc),
            "spawn_error",
            f"provider failed to start: {exc}",
            schema_mode="native",
            elapsed_seconds=elapsed,
            command_argv=tuple(command),
        )

    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        return ProviderRunResult(
            status.provider_id,
            None,
            completed.stdout or "",
            completed.stderr or "",
            "provider_error",
            f"provider exited {completed.returncode}",
            schema_mode="native",
            elapsed_seconds=elapsed,
            command_argv=tuple(command),
            returncode=completed.returncode,
        )
    try:
        payload = _claude_output_payload(completed.stdout or "")
    except (json.JSONDecodeError, ProviderReviewSchemaError) as exc:
        if allow_parser_fallback:
            fallback = _try_parser_fallback_result(
                provider_id=status.provider_id,
                native_error=exc,
                raw_text=_fallback_raw_text(completed.stdout, completed.stderr),
                stdout_text=completed.stdout or "",
                stderr_text=completed.stderr or "",
                elapsed_seconds=elapsed,
                command_argv=command,
                returncode=completed.returncode,
            )
            if fallback is not None:
                return fallback
        return ProviderRunResult(
            status.provider_id,
            None,
            completed.stdout or "",
            completed.stderr or "",
            "malformed_output",
            str(exc),
            schema_mode="native",
            elapsed_seconds=elapsed,
            command_argv=tuple(command),
            returncode=completed.returncode,
        )
    return ProviderRunResult(
        status.provider_id,
        payload,
        completed.stdout or "",
        completed.stderr or "",
        schema_mode="native",
        elapsed_seconds=elapsed,
        last_message_text=json.dumps(payload, sort_keys=True) + "\n",
        command_argv=tuple(command),
        returncode=completed.returncode,
    )


def _run_real_provider(
    provider_id: str,
    status: ReviewProviderStatus | None,
    *,
    repo: Path,
    prompt_text: str,
    output_dir: Path,
    timeout_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    allow_parser_fallback: bool = False,
) -> ProviderRunResult:
    if status is None or not status.eligible:
        return ProviderRunResult(
            provider_id,
            None,
            "",
            "",
            "not_eligible",
            "provider was selected without a ready eligibility probe",
        )
    if status.fake:
        return ProviderRunResult(
            provider_id,
            None,
            "",
            "",
            "configuration_error",
            "fake provider selected without --fake-result-dir",
        )
    provider_dir = output_dir / "providers" / _safe_provider_dir(provider_id)
    provider_dir.mkdir(parents=True, exist_ok=True)
    if provider_id == "codex":
        return _run_codex_review_provider(
            status,
            repo=repo,
            prompt_text=prompt_text,
            provider_dir=provider_dir,
            timeout_seconds=timeout_seconds,
            runner=runner,
            allow_parser_fallback=allow_parser_fallback,
        )
    if provider_id == "claude":
        return _run_claude_review_provider(
            status,
            repo=repo,
            prompt_text=prompt_text,
            timeout_seconds=timeout_seconds,
            runner=runner,
            allow_parser_fallback=allow_parser_fallback,
        )
    return ProviderRunResult(
        provider_id,
        None,
        "",
        "",
        "unsupported_provider",
        f"no real provider execution shim registered for {provider_id}",
    )


def _run_fake_provider(
    provider_id: str,
    fake_result_dir: Path,
    provider_dir: Path,
    timeout_seconds: int,
    allow_parser_fallback: bool = False,
) -> ProviderRunResult:
    started = time.monotonic()
    path = _fake_payload_path(fake_result_dir, provider_id)
    if not path.is_file():
        return ProviderRunResult(provider_id, None, "", f"missing fake result: {path}", "spawn_error", f"missing fake result: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        if allow_parser_fallback:
            elapsed = time.monotonic() - started
            fallback = _try_parser_fallback_result(
                provider_id=provider_id,
                native_error=exc,
                raw_text=raw_text,
                stdout_text=raw_text,
                stderr_text="",
                elapsed_seconds=elapsed,
            )
            if fallback is not None:
                return fallback
        return ProviderRunResult(provider_id, None, "", str(exc), "malformed_output", f"fake result is not JSON: {exc}")
    if isinstance(payload, Mapping):
        sleep_seconds = payload.get("_fake_sleep_seconds")
        if isinstance(sleep_seconds, (int, float)) and sleep_seconds > timeout_seconds:
            return ProviderRunResult(provider_id, None, "", "fake timeout", "timeout", f"provider timed out after {timeout_seconds}s")
        fake_error = payload.get("_fake_error")
        if isinstance(fake_error, Mapping):
            return ProviderRunResult(
                provider_id,
                payload,
                json.dumps(payload, sort_keys=True) + "\n",
                str(fake_error.get("message") or ""),
                str(fake_error.get("class") or "error"),
                str(fake_error.get("message") or "fake provider error"),
            )
    stdout = json.dumps(payload, sort_keys=True) + "\n"
    elapsed = time.monotonic() - started
    return ProviderRunResult(provider_id, payload, stdout, "", elapsed_seconds=elapsed)


def _write_provider_sidecars(output_dir: Path, result: ProviderRunResult) -> ProviderRunResult:
    provider_dir = output_dir / "providers" / _safe_provider_dir(result.provider_id)
    stdout_path = provider_dir / "stdout.jsonl"
    stderr_path = provider_dir / "stderr.txt"
    last_message_path = provider_dir / "last-message.json"
    meta_path = provider_dir / "meta.json"
    _write_text(stdout_path, result.stdout_text)
    _write_text(stderr_path, result.stderr_text)
    if result.last_message_text is None:
        _write_json(last_message_path, result.payload)
    else:
        _write_text(last_message_path, result.last_message_text)
    meta: dict[str, Any] = {
        "provider_id": result.provider_id,
        "status": "ok" if result.ok else "error",
        "error_class": result.error_class,
        "message": result.message,
        "schema_mode": result.schema_mode,
        "elapsed_seconds": round(result.elapsed_seconds, 6),
    }
    if result.returncode is not None:
        meta["returncode"] = result.returncode
    if result.command_argv:
        meta["command_argv"] = _redacted_argv(result.command_argv)
    _write_json(
        meta_path,
        meta,
    )
    return dataclasses.replace(result, sidecar_path=str(provider_dir))


def _run_selected_fake_providers(
    provider_ids: Sequence[str],
    *,
    fake_result_dir: Path,
    output_dir: Path,
    timeout_seconds: int,
    max_parallel: int,
    allow_parser_fallback: bool = False,
) -> list[ProviderRunResult]:
    results: list[ProviderRunResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_parallel)) as executor:
        future_map = {
            executor.submit(
                _run_fake_provider,
                provider_id,
                fake_result_dir,
                output_dir / "providers" / _safe_provider_dir(provider_id),
                timeout_seconds,
                allow_parser_fallback,
            ): provider_id
            for provider_id in provider_ids
        }
        for future in concurrent.futures.as_completed(future_map):
            try:
                result = future.result(timeout=timeout_seconds + 1)
            except Exception as exc:
                provider_id = future_map[future]
                result = ProviderRunResult(provider_id, None, "", str(exc), "spawn_error", str(exc))
            results.append(_write_provider_sidecars(output_dir, result))
    return sorted(results, key=lambda result: provider_ids.index(result.provider_id))


def _run_selected_real_providers(
    provider_ids: Sequence[str],
    *,
    provider_statuses: Sequence[ReviewProviderStatus],
    repo: Path,
    prompt_file: Path,
    output_dir: Path,
    timeout_seconds: int,
    max_parallel: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    allow_parser_fallback: bool = False,
) -> list[ProviderRunResult]:
    prompt_text = prompt_file.read_text(encoding="utf-8")
    status_by_id = {status.provider_id: status for status in provider_statuses}
    results: list[ProviderRunResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_parallel)) as executor:
        future_map = {
            executor.submit(
                _run_real_provider,
                provider_id,
                status_by_id.get(provider_id),
                repo=repo,
                prompt_text=prompt_text,
                output_dir=output_dir,
                timeout_seconds=timeout_seconds,
                runner=runner,
                allow_parser_fallback=allow_parser_fallback,
            ): provider_id
            for provider_id in provider_ids
        }
        for future in concurrent.futures.as_completed(future_map):
            try:
                result = future.result(timeout=timeout_seconds + 1)
            except Exception as exc:
                provider_id = future_map[future]
                result = ProviderRunResult(provider_id, None, "", str(exc), "spawn_error", str(exc))
            results.append(_write_provider_sidecars(output_dir, result))
    return sorted(results, key=lambda result: provider_ids.index(result.provider_id))


def write_manifest(
    *,
    path: Path,
    selection: ReviewSelectionResult,
    prompt_file: Path,
    output_dir: Path,
    timeout_seconds: int,
    command_argv: Sequence[str],
    allow_parser_fallback: bool = False,
) -> dict[str, Any]:
    manifest = {
        "schema_version": "provider-review.manifest.v1",
        "prompt_path": str(prompt_file),
        "prompt_hash": _prompt_hash(prompt_file),
        "emission_schema": str(EMISSION_SCHEMA_PATH),
        "provider_findings_schema": str(PROVIDER_FINDINGS_V2_SCHEMA_PATH),
        "timeout_seconds": timeout_seconds,
        "selection": selection.as_dict(),
        "command_argv": _redacted_argv(command_argv),
        "parser_fallback": {
            "enabled": allow_parser_fallback,
            "mode": "experiment" if allow_parser_fallback else "off",
            "stock_auto_allowed": False,
            "confidence_cap": PARSER_FALLBACK_CONFIDENCE_CAP,
        },
        "raw_sidecars": str(output_dir / "providers"),
        "retention": {
            "class": "local-run-artifact-sensitive",
            "policy": "retained or purged with the run artifact directory; not promoted to telemetry",
        },
    }
    _write_json(path, manifest)
    return manifest


def run_stage(args: argparse.Namespace) -> int:
    if args.command != "review":
        raise ProviderReviewError("only --command review is supported")
    if args.timeout_seconds < 1:
        raise ProviderReviewError("--timeout-seconds must be >= 1")
    min_success_override = getattr(args, "min_success", None)
    if min_success_override is not None and min_success_override < 1:
        raise ProviderReviewError("--min-success must be >= 1")
    repo = Path(args.repo).resolve()
    prompt_file = Path(args.prompt_file).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "provider-findings.json"
    manifest_path = output_dir / "provider-review.manifest.json"
    explicit = parse_provider_csv(args.providers)
    allow_parser_fallback = bool(getattr(args, "allow_parser_fallback", False))
    if allow_parser_fallback:
        if args.selection != "explicit":
            raise ProviderReviewError("--allow-parser-fallback requires --selection explicit")
        if not explicit:
            raise ProviderReviewError("--allow-parser-fallback requires --providers")
    fake_result_dir = Path(args.fake_result_dir).resolve() if args.fake_result_dir else None
    fake_providers = explicit if fake_result_dir is not None and explicit else None
    runner = getattr(args, "runner", subprocess.run)
    resolver = getattr(args, "resolver", None) or ReviewProviderResolver(fake_providers=fake_providers, runner=runner)
    selection = resolver.select(
        selection=args.selection,
        explicit_providers=explicit,
        max_parallel=args.max_parallel,
    )
    if min_success_override is not None:
        selection = dataclasses.replace(
            selection,
            policy=dataclasses.replace(selection.policy, min_success=min_success_override),
        )
    write_manifest(
        path=manifest_path,
        selection=selection,
        prompt_file=prompt_file,
        output_dir=output_dir,
        timeout_seconds=args.timeout_seconds,
        command_argv=sys.argv,
        allow_parser_fallback=allow_parser_fallback,
    )

    if not selection.selected_providers:
        artifact = skipped_result(
            run_id=args.run_id,
            issue_id=args.issue_id,
            stage_id=args.stage_id,
            configured_providers=selection.configured_providers,
            selected_providers=selection.selected_providers,
            source_artifact_path=str(result_path),
            manifest_path=str(manifest_path),
            min_success=selection.policy.min_success,
            selection_result=selection.selection_result,
        )
        validate_provider_findings_v2_artifact(artifact)
        _write_json(result_path, artifact)
        print(str(result_path))
        return 0

    if fake_result_dir is None:
        results = _run_selected_real_providers(
            selection.selected_providers,
            provider_statuses=selection.provider_statuses,
            repo=repo,
            prompt_file=prompt_file,
            output_dir=output_dir,
            timeout_seconds=args.timeout_seconds,
            max_parallel=selection.policy.max_parallel,
            runner=runner,
            allow_parser_fallback=allow_parser_fallback,
        )
    else:
        results = _run_selected_fake_providers(
            selection.selected_providers,
            fake_result_dir=fake_result_dir,
            output_dir=output_dir,
            timeout_seconds=args.timeout_seconds,
            max_parallel=selection.policy.max_parallel,
            allow_parser_fallback=allow_parser_fallback,
        )
    artifact = normalize_provider_review_results(
        results,
        run_id=args.run_id,
        issue_id=args.issue_id,
        stage_id=args.stage_id,
        configured_providers=selection.configured_providers,
        selected_providers=selection.selected_providers,
        source_artifact_path=str(result_path),
        manifest_path=str(manifest_path),
        min_success=selection.policy.min_success,
        selection_result=selection.selection_result,
    )
    validate_provider_findings_v2_artifact(artifact)
    _write_json(result_path, artifact)
    print(str(result_path))
    return 0 if artifact["status"] in {"ok", "partial", "skipped"} else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm-provider-review")
    parser.add_argument("--repo", required=True, help="repository root to review")
    parser.add_argument("--prompt-file", required=True, help="provider review prompt file")
    parser.add_argument("--command", choices=["review"], default="review")
    parser.add_argument("--selection", choices=sorted(SELECTIONS), default="auto")
    parser.add_argument("--providers", help="comma-separated provider allowlist for selection=explicit")
    parser.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL)
    parser.add_argument("--min-success", type=int)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output-dir", required=True, help="swarm run artifact directory for provider review")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--issue-id", required=True)
    parser.add_argument("--stage-id", default="provider-review")
    parser.add_argument(
        "--allow-parser-fallback",
        action="store_true",
        help="enable explicit experiment-mode parsing after native schema failure; requires selection=explicit",
    )
    parser.add_argument("--fake-result-dir", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return run_stage(args)
    except ProviderReviewError as exc:
        print(f"swarm-provider-review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
