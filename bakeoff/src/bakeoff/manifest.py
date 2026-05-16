from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from bakeoff import __version__
from bakeoff.triage import triage_state_detail
from bakeoff.work_order import TRIAGE_CLASSIFICATIONS, ValidationError

MANIFEST_SCHEMA_VERSION = 1
FINGERPRINT_ARTIFACTS = (
    "work-order.json",
    "source-work-order.json",
    "review-context.md",
    "review-context.json",
    "decision.json",
    "meta.json",
    "report.md",
    "triage/status.json",
    "triage/final.json",
    "triage/triage.md",
)
REQUIRED_ARTIFACTS = ("work-order.json", "decision.json", "meta.json", "report.md")


def build_run_manifest(run_dir: Path) -> dict[str, Any]:
    work_order = _read_required_json(run_dir / "work-order.json")
    decision = _read_required_json(run_dir / "decision.json")
    meta = _read_required_json(run_dir / "meta.json")
    _require_file(run_dir / "report.md")

    facet = meta.get("facet") if isinstance(meta.get("facet"), dict) else work_order.get("facet")
    facet_id = facet.get("id") if isinstance(facet, dict) and isinstance(facet.get("id"), str) else None
    state, stale_inputs = triage_state_detail(run_dir)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_dir.name,
        "bakeoff_version": __version__,
        "type": meta.get("type", work_order.get("type")),
        "facet_id": facet_id,
        "started_at": meta.get("started_at"),
        "finished_at": meta.get("finished_at"),
        "cwd": meta.get("cwd"),
        "decision_kind": decision.get("decision_kind"),
        "canonical_winner": decision.get("canonical_winner"),
        "judge_ran": bool(decision.get("judge_ran")),
        "triage": _triage_summary(run_dir, state, stale_inputs),
        "providers": _provider_summaries(meta, decision),
        "judge": _judge_summary(meta),
        "review_context": _review_context_summary(run_dir),
        "artifacts": _artifact_paths(run_dir),
        "artifact_fingerprints": _artifact_fingerprints(run_dir),
    }
    return manifest


def write_run_manifest(run_dir: Path) -> dict[str, Any]:
    manifest = build_run_manifest(run_dir)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=run_dir,
            prefix=".manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(text)
        os.replace(tmp_name, run_dir / "manifest.json")
        tmp_name = ""
    finally:
        if tmp_name:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass

    return manifest


def manifest_row_for_ls(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return _legacy_ls_row(run_dir, manifest_state="missing")
    try:
        manifest = _read_required_json(manifest_path)
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValidationError("schema_version is not 1")
        if manifest.get("run_id") != run_dir.name:
            raise ValidationError("run_id does not match directory name")
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        current_triage_state, _ = triage_state_detail(run_dir)
        row = {
            "run_id": run_dir.name,
            "manifest_state": "present",
            "type": manifest.get("type"),
            "facet_id": manifest.get("facet_id"),
            "decision_kind": manifest.get("decision_kind"),
            "triage_state": current_triage_state or _manifest_triage_state(manifest),
            "finished_at": manifest.get("finished_at"),
            "manifest_path": str(manifest_path),
        }
        if isinstance(artifacts.get("report"), str):
            row["report_path"] = str(run_dir / artifacts["report"])
        elif (run_dir / "report.md").exists():
            row["report_path"] = str(run_dir / "report.md")
        return row
    except (ValidationError, json.JSONDecodeError, OSError) as exc:
        row = _legacy_ls_row(run_dir, manifest_state="invalid")
        row["manifest_path"] = str(manifest_path)
        row["manifest_error"] = _short_error(exc)
        return row


def _triage_summary(run_dir: Path, state: str, stale_inputs: list[str]) -> dict[str, Any]:
    triage_dir = run_dir / "triage"
    status = _read_json(triage_dir / "status.json")
    final = _read_json(triage_dir / "final.json")
    summary: dict[str, Any] = {
        "state": state,
        "stale_inputs": stale_inputs,
    }
    if isinstance(status, dict) and isinstance(status.get("status"), str):
        summary["attempt_status"] = status["status"]
    input_hashes = None
    if isinstance(status, dict) and isinstance(status.get("input_hashes"), dict):
        input_hashes = status["input_hashes"]
    elif isinstance(final, dict) and isinstance(final.get("input_hashes"), dict):
        input_hashes = final["input_hashes"]
    if input_hashes is not None:
        summary["input_hashes"] = input_hashes
    if isinstance(final, dict):
        items = final.get("items") if isinstance(final.get("items"), list) else []
        summary["item_count"] = len(items)
        summary["item_counts_by_classification"] = _classification_counts(items)
        summary["highest_severity"] = _highest_severity(items)
    return summary


def _provider_summaries(meta: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    resolved = meta.get("resolved_models") if isinstance(meta.get("resolved_models"), dict) else {}
    resolved_providers = resolved.get("providers") if isinstance(resolved.get("providers"), dict) else {}
    statuses = decision.get("provider_statuses") if isinstance(decision.get("provider_statuses"), dict) else {}
    providers: dict[str, Any] = {}
    for provider_id in sorted(set(resolved_providers) | set(statuses)):
        model_info = resolved_providers.get(provider_id) if isinstance(resolved_providers.get(provider_id), dict) else {}
        status_info = statuses.get(provider_id) if isinstance(statuses.get(provider_id), dict) else {}
        summary = {
            "backend": model_info.get("backend"),
            "model": model_info.get("model"),
            "scope": model_info.get("scope"),
            "effort": model_info.get("effort"),
            "status": status_info.get("status"),
            "wall_seconds": status_info.get("wall_seconds"),
            "stdout_bytes": status_info.get("stdout_bytes", status_info.get("output_bytes")),
            "stderr_bytes": status_info.get("stderr_bytes"),
        }
        if "final_json_source" in status_info:
            summary["final_json_source"] = status_info["final_json_source"]
        providers[provider_id] = {key: value for key, value in summary.items() if value is not None}
    return providers


def _judge_summary(meta: dict[str, Any]) -> dict[str, Any]:
    resolved = meta.get("resolved_models") if isinstance(meta.get("resolved_models"), dict) else {}
    judge = resolved.get("judge") if isinstance(resolved.get("judge"), dict) else {}
    return {
        key: judge[key]
        for key in ("backend", "model", "effort")
        if key in judge
    }


def _review_context_summary(run_dir: Path) -> dict[str, Any]:
    context = _read_json(run_dir / "review-context.json")
    if isinstance(context, dict):
        return {
            "present": True,
            **{
                key: context[key]
                for key in (
                    "base_ref",
                    "base_commit",
                    "head_commit",
                    "git_root",
                    "capture_cwd",
                    "pathspec",
                    "included_sections",
                )
                if key in context
            },
        }
    return {"present": False}


def _artifact_paths(run_dir: Path) -> dict[str, str]:
    for relative in REQUIRED_ARTIFACTS:
        _require_file(run_dir / relative)
    artifacts = {
        "work_order": "work-order.json",
        "decision": "decision.json",
        "report": "report.md",
        "meta": "meta.json",
    }
    optional = {
        "source_work_order": "source-work-order.json",
        "review_context_md": "review-context.md",
        "review_context_json": "review-context.json",
        "triage": "triage/triage.md",
    }
    for key, relative in optional.items():
        if (run_dir / relative).exists():
            artifacts[key] = relative
    return artifacts


def _artifact_fingerprints(run_dir: Path) -> dict[str, Any]:
    fingerprints = {}
    for relative in FINGERPRINT_ARTIFACTS:
        path = run_dir / relative
        if not path.exists():
            if relative in REQUIRED_ARTIFACTS:
                raise ValidationError(f"{path} is required for manifest")
            continue
        fingerprints[relative] = _fingerprint(path)
    return fingerprints


def _fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _classification_counts(items: list[Any]) -> dict[str, int]:
    counts = {classification: 0 for classification in TRIAGE_CLASSIFICATIONS}
    for item in items:
        if isinstance(item, dict) and item.get("classification") in counts:
            counts[item["classification"]] += 1
    return counts


def _highest_severity(items: list[Any]) -> str | None:
    if not items:
        return None
    severities = {item.get("severity") for item in items if isinstance(item, dict)}
    for severity in ("high", "medium", "low", "none"):
        if severity in severities:
            return severity
    return None


def _legacy_ls_row(run_dir: Path, *, manifest_state: str) -> dict[str, Any]:
    try:
        meta = _read_json(run_dir / "meta.json")
    except ValidationError:
        meta = {}
    try:
        decision = _read_json(run_dir / "decision.json")
    except ValidationError:
        decision = {}
    meta = meta if isinstance(meta, dict) else {}
    decision = decision if isinstance(decision, dict) else {}
    facet = meta.get("facet")
    facet_id = facet.get("id") if isinstance(facet, dict) and isinstance(facet.get("id"), str) else None
    state, _ = triage_state_detail(run_dir)
    row = {
        "run_id": run_dir.name,
        "manifest_state": manifest_state,
        "type": meta.get("type"),
        "facet_id": facet_id,
        "decision_kind": decision.get("decision_kind"),
        "triage_state": state,
        "finished_at": meta.get("finished_at"),
    }
    if (run_dir / "report.md").exists():
        row["report_path"] = str(run_dir / "report.md")
    return row


def _manifest_triage_state(manifest: dict[str, Any]) -> Any:
    triage = manifest.get("triage")
    if isinstance(triage, dict):
        return triage.get("state")
    return None


def _read_required_json(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"{path} is required and must be a JSON object")
    return value


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is invalid JSON: {exc.msg}") from exc


def _require_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise ValidationError(f"{path} is required for manifest")


def _short_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:240] if len(text) > 240 else text
