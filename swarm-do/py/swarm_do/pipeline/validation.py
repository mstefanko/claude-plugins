"""Validation gates for preset and pipeline loading."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .catalog import AGENTS_LENS_STACKING_ERROR, get_lens, validate_prompt_lens_selection
from .engine import BudgetPreview, budget_preview, topological_layers
from .paths import REPO_ROOT
from .registry import find_pipeline, find_preset, load_pipeline, load_preset
from .resolver import BACKENDS, EFFORTS, BackendResolver


VARIANTS = {"same", "prompt_variants", "models"}
MERGE_STRATEGIES = {"synthesize", "vote"}
TOLERANCE_MODES = {"strict", "quorum", "best-effort"}
PIPELINE_TOP_KEYS = {
    "pipeline_version",
    "name",
    "description",
    "origin",
    "forked_from",
    "forked_from_hash",
    "generated_by",
    "parallelism",
    "stages",
}
PRESET_TOP_KEYS = {
    "name",
    "description",
    "pipeline",
    "origin",
    "forked_from",
    "routing",
    "budget",
    "decompose",
    "mem_prime",
    "review_providers",
    "forked_from_hash",
    "generated_by",
}
STAGE_KEYS = {"id", "depends_on", "agents", "fan_out", "provider", "merge", "failure_tolerance"}
FAN_OUT_KEYS = {"role", "count", "variant", "variants", "routes"}
MERGE_KEYS = {"strategy", "agent"}
AGENT_KEYS = {"role", "backend", "model", "effort", "route", "lens"}
UNSUPPORTED_AGENT_KEYS = {"lenses"}
PROVIDER_KEYS = {
    "type",
    "command",
    "providers",
    "selection",
    "mode",
    "strict_contract",
    "output",
    "memory",
    "timeout_seconds",
    "max_parallel",
}
PROVIDER_TYPES = {"mco", "swarm-review"}
PROVIDER_COMMANDS = {"review"}
PROVIDER_MODES = {"review", "debate", "divide"}
PROVIDER_OUTPUTS = {"findings"}
REVIEW_PROVIDER_SELECTIONS = {"auto", "explicit", "off"}
MCO_PROVIDER_ORDER = ("claude", "codex", "gemini", "opencode", "qwen")
MCO_PROVIDERS = set(MCO_PROVIDER_ORDER)
REVIEW_PROVIDER_POLICY_KEYS = {"selection", "min_success", "max_parallel", "include", "exclude"}
WORK_UNIT_TOP_KEYS = {"schema_version", "plan_path", "bd_epic_id", "work_units"}
WORK_UNIT_KEYS = {
    "id",
    "title",
    "goal",
    "depends_on",
    "files",
    "context_files",
    "allowed_files",
    "blocked_files",
    "acceptance_criteria",
    "validation_commands",
    "expected_results",
    "risk_tags",
    "handoff_notes",
    "mem_prime",
    "beads_id",
    "worktree_branch",
    "status",
    "failure_reason",
    "retry_count",
    "handoff_count",
}
WORK_UNIT_V1_REQUIRED_KEYS = {
    "id",
    "depends_on",
    "files",
    "acceptance_criteria",
    "beads_id",
    "worktree_branch",
    "status",
    "retry_count",
    "handoff_count",
}
WORK_UNIT_V2_REQUIRED_KEYS = {
    "id",
    "title",
    "goal",
    "depends_on",
    "context_files",
    "blocked_files",
    "acceptance_criteria",
    "validation_commands",
    "expected_results",
    "risk_tags",
    "handoff_notes",
    "beads_id",
    "worktree_branch",
    "status",
    "failure_reason",
    "retry_count",
    "handoff_count",
}
WORK_UNIT_STATUSES = {"pending", "running", "blocked", "approved", "merged", "failed", "escalated"}
WORK_UNIT_FAILURE_REASONS = {
    None,
    "budget_breach_tool_calls",
    "budget_breach_output_bytes",
    "blocked_file_violation",
    "spec_mismatch_max",
    "repeat_handoff",
    "mem_prime_failure",
    "dependency_failed",
    "other",
}
DECOMPOSE_MODES = {"off", "inspect", "enforce"}
MEM_PRIME_MODES = {"off", "hard_only", "on"}
MEM_PRIME_ADAPTERS = {"dispatch_file", "local_sqlite"}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    budget: BudgetPreview | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, message: str) -> None:
        self.errors.append(message)


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _role_exists(role: str) -> bool:
    if role == "orchestrator":
        return True
    return (REPO_ROOT / "agents" / f"{role}.md").is_file()


def _all_roles(pipeline: Mapping[str, Any]) -> list[str]:
    roles: list[str] = []
    for stage in pipeline.get("stages") or []:
        for agent in stage.get("agents") or []:
            if isinstance(agent, Mapping) and isinstance(agent.get("role"), str):
                roles.append(agent["role"])
        fan = stage.get("fan_out")
        if isinstance(fan, Mapping) and isinstance(fan.get("role"), str):
            roles.append(fan["role"])
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and isinstance(merge.get("agent"), str):
            roles.append(merge["agent"])
    return roles


def _provider_branch_count(stage: Mapping[str, Any]) -> int:
    provider = stage.get("provider")
    if isinstance(provider, Mapping):
        if provider.get("type") == "swarm-review":
            selection = provider.get("selection", "auto")
            if selection == "off":
                return 0
            if selection == "explicit" and isinstance(provider.get("providers"), list):
                return len(provider["providers"])
            max_parallel = provider.get("max_parallel")
            return max_parallel if isinstance(max_parallel, int) and max_parallel > 0 else 4
        if isinstance(provider.get("providers"), list):
            return len(provider["providers"])
    return 1


def schema_lint_preset(preset: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(preset.keys()) - PRESET_TOP_KEYS)
    if unknown:
        errors.append(f"preset: unknown top-level keys: {', '.join(unknown)}")
    for key in ("name", "pipeline"):
        if not isinstance(preset.get(key), str) or not preset.get(key):
            errors.append(f"preset: {key} must be a non-empty string")
    if "origin" in preset and preset["origin"] not in {"stock", "user", "experiment"}:
        errors.append("preset: origin must be stock, user, or experiment")
    for key in ("forked_from", "forked_from_hash", "generated_by"):
        if key in preset and not isinstance(preset.get(key), str):
            errors.append(f"preset: {key} must be a string")
    if isinstance(preset.get("forked_from_hash"), str) and not preset["forked_from_hash"].startswith("sha256:"):
        errors.append("preset: forked_from_hash must start with sha256:")
    if "routing" in preset and not isinstance(preset["routing"], Mapping):
        errors.append("preset: routing must be a table")
    budget = preset.get("budget")
    if not isinstance(budget, Mapping):
        errors.append("preset: budget table is required")
    else:
        for key in ("max_agents_per_run", "max_wall_clock_seconds"):
            if not isinstance(budget.get(key), int):
                errors.append(f"preset: budget.{key} must be an integer")
        if not isinstance(budget.get("max_estimated_cost_usd"), (int, float)):
            errors.append("preset: budget.max_estimated_cost_usd must be a number")
        for key in ("max_writer_tool_calls", "max_writer_output_bytes", "max_handoffs"):
            if key in budget and (not isinstance(budget.get(key), int) or budget.get(key) < 0):
                errors.append(f"preset: budget.{key} must be a non-negative integer")
    decompose = preset.get("decompose")
    if decompose is not None:
        if not isinstance(decompose, Mapping):
            errors.append("preset: decompose must be a table")
        elif decompose.get("mode") not in DECOMPOSE_MODES:
            errors.append(f"preset: decompose.mode must be one of {sorted(DECOMPOSE_MODES)}")
    mem_prime = preset.get("mem_prime")
    if mem_prime is not None:
        if not isinstance(mem_prime, Mapping):
            errors.append("preset: mem_prime must be a table")
        else:
            if mem_prime.get("mode") not in MEM_PRIME_MODES:
                errors.append(f"preset: mem_prime.mode must be one of {sorted(MEM_PRIME_MODES)}")
            for key in ("max_tokens", "recency_days"):
                if key in mem_prime and (not isinstance(mem_prime.get(key), int) or mem_prime.get(key) < 0):
                    errors.append(f"preset: mem_prime.{key} must be a non-negative integer")
            if "min_relevance" in mem_prime and not isinstance(mem_prime.get("min_relevance"), (int, float)):
                errors.append("preset: mem_prime.min_relevance must be a number")
            if "adapter" in mem_prime and mem_prime.get("adapter") not in MEM_PRIME_ADAPTERS:
                errors.append(f"preset: mem_prime.adapter must be one of {sorted(MEM_PRIME_ADAPTERS)}")
    review_providers = preset.get("review_providers")
    if review_providers is not None:
        if not isinstance(review_providers, Mapping):
            errors.append("preset: review_providers must be a table")
        else:
            unknown_review = sorted(set(review_providers.keys()) - REVIEW_PROVIDER_POLICY_KEYS)
            if unknown_review:
                errors.append(
                    "preset: review_providers supports only run-shaping policy keys; "
                    f"unknown keys: {', '.join(unknown_review)}"
                )
            if "selection" in review_providers and review_providers.get("selection") not in REVIEW_PROVIDER_SELECTIONS:
                errors.append(f"preset: review_providers.selection must be one of {sorted(REVIEW_PROVIDER_SELECTIONS)}")
            for key in ("include", "exclude"):
                if key in review_providers and not _is_str_list(review_providers.get(key)):
                    errors.append(f"preset: review_providers.{key} must be an array of strings")
            for key in ("min_success", "max_parallel"):
                if key in review_providers and (
                    not isinstance(review_providers.get(key), int) or review_providers.get(key) < 1
                ):
                    errors.append(f"preset: review_providers.{key} must be a positive integer")
    return errors


def _lint_route(route: Any, path: str) -> list[str]:
    errors: list[str] = []
    if isinstance(route, str):
        return errors
    if not isinstance(route, Mapping):
        return [f"{path}: route must be an object or named preset route"]
    if route.get("backend") not in BACKENDS:
        errors.append(f"{path}.backend must be one of {sorted(BACKENDS)}")
    if not isinstance(route.get("model"), str) or not route.get("model"):
        errors.append(f"{path}.model must be a non-empty string")
    if route.get("effort") not in EFFORTS:
        errors.append(f"{path}.effort must be one of {sorted(EFFORTS)}")
    return errors


def schema_lint_pipeline(pipeline: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(pipeline.keys()) - PIPELINE_TOP_KEYS)
    if unknown:
        errors.append(f"pipeline: unknown top-level keys: {', '.join(unknown)}")
    if not isinstance(pipeline.get("pipeline_version"), int):
        errors.append("pipeline: pipeline_version must be an integer")
    if not isinstance(pipeline.get("name"), str) or not pipeline.get("name"):
        errors.append("pipeline: name must be a non-empty string")
    if "origin" in pipeline and pipeline["origin"] not in {"stock", "user", "experiment"}:
        errors.append("pipeline: origin must be stock, user, or experiment")
    for key in ("forked_from", "forked_from_hash", "generated_by"):
        if key in pipeline and not isinstance(pipeline.get(key), str):
            errors.append(f"pipeline: {key} must be a string")
    if isinstance(pipeline.get("forked_from_hash"), str) and not pipeline["forked_from_hash"].startswith("sha256:"):
        errors.append("pipeline: forked_from_hash must start with sha256:")
    if "parallelism" in pipeline:
        parallelism = pipeline.get("parallelism")
        if not isinstance(parallelism, int) or parallelism < 1 or parallelism > 32:
            errors.append("pipeline: parallelism must be an integer from 1 to 32")
    stages = pipeline.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("pipeline: stages must be a non-empty array")
        return errors

    ids: set[str] = set()
    for idx, stage in enumerate(stages):
        path = f"pipeline.stages[{idx}]"
        if not isinstance(stage, Mapping):
            errors.append(f"{path}: stage must be an object")
            continue
        unknown_stage = sorted(set(stage.keys()) - STAGE_KEYS)
        if unknown_stage:
            errors.append(f"{path}: unknown keys: {', '.join(unknown_stage)}")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            errors.append(f"{path}.id must be a non-empty string")
        elif stage_id in ids:
            errors.append(f"{path}.id duplicates stage id {stage_id}")
        else:
            ids.add(stage_id)
        deps = stage.get("depends_on", [])
        if deps is None:
            deps = []
        if not _is_str_list(deps):
            errors.append(f"{path}.depends_on must be an array of stage ids")
        has_agents = "agents" in stage
        has_fan = "fan_out" in stage
        has_provider = "provider" in stage
        if sum(1 for present in (has_agents, has_fan, has_provider) if present) != 1:
            errors.append(f"{path}: exactly one of agents, fan_out, or provider is required")
        if has_agents:
            agents = stage.get("agents")
            if not isinstance(agents, list) or not agents:
                errors.append(f"{path}.agents must be a non-empty array")
            else:
                for a_idx, agent in enumerate(agents):
                    a_path = f"{path}.agents[{a_idx}]"
                    if not isinstance(agent, Mapping):
                        errors.append(f"{a_path}: agent must be an object")
                        continue
                    if "lenses" in agent:
                        errors.append(f"{a_path}.lenses is not supported; {AGENTS_LENS_STACKING_ERROR}")
                    unknown_agent = sorted(set(agent.keys()) - AGENT_KEYS - UNSUPPORTED_AGENT_KEYS)
                    if unknown_agent:
                        errors.append(f"{a_path}: unknown keys: {', '.join(unknown_agent)}")
                    if not isinstance(agent.get("role"), str) or not agent.get("role"):
                        errors.append(f"{a_path}.role must be a non-empty string")
                    elif "lens" in agent:
                        lens_id = agent.get("lens")
                        if not isinstance(lens_id, str) or not lens_id:
                            errors.append(f"{a_path}.lens must be a non-empty string")
                        else:
                            for error in validate_prompt_lens_selection(
                                agent["role"],
                                [lens_id],
                                stage_kind="agents",
                                require_files=False,
                            ):
                                errors.append(f"{a_path}.lens: {error}")
                    override_keys = {k for k in ("backend", "model", "effort") if k in agent}
                    if override_keys and override_keys != {"backend", "model", "effort"}:
                        errors.append(f"{a_path}: backend/model/effort overrides must be supplied together")
                    if override_keys:
                        errors.extend(_lint_route(agent, a_path))
        if has_fan:
            fan = stage.get("fan_out")
            if not isinstance(fan, Mapping):
                errors.append(f"{path}.fan_out must be an object")
            else:
                unknown_fan = sorted(set(fan.keys()) - FAN_OUT_KEYS)
                if unknown_fan:
                    errors.append(f"{path}.fan_out: unknown keys: {', '.join(unknown_fan)}")
                if not isinstance(fan.get("role"), str) or not fan.get("role"):
                    errors.append(f"{path}.fan_out.role must be a non-empty string")
                count = fan.get("count")
                if not isinstance(count, int) or not (1 <= count <= 10):
                    errors.append(f"{path}.fan_out.count must be an integer from 1 to 10")
                variant = fan.get("variant")
                if variant not in VARIANTS:
                    errors.append(f"{path}.fan_out.variant must be one of {sorted(VARIANTS)}")
                if variant == "prompt_variants":
                    variants = fan.get("variants")
                    if not _is_str_list(variants) or len(variants) != count:
                        errors.append(f"{path}.fan_out.variants must be an array of count strings")
                if variant == "models":
                    routes = fan.get("routes")
                    if not isinstance(routes, list) or len(routes) != count:
                        errors.append(f"{path}.fan_out.routes must be an array with count entries")
                    else:
                        for r_idx, route in enumerate(routes):
                            if isinstance(route, str) and any(ch in route for ch in ("/", ".")):
                                errors.append(f"{path}.fan_out.routes[{r_idx}]: bare model IDs are invalid; use route objects")
                            errors.extend(_lint_route(route, f"{path}.fan_out.routes[{r_idx}]"))
            if "merge" not in stage:
                errors.append(f"{path}: fan_out stages require merge")
        if has_provider:
            provider = stage.get("provider")
            if not isinstance(provider, Mapping):
                errors.append(f"{path}.provider must be an object")
            else:
                unknown_provider = sorted(set(provider.keys()) - PROVIDER_KEYS)
                if unknown_provider:
                    errors.append(f"{path}.provider: unknown keys: {', '.join(unknown_provider)}")
                if provider.get("type") not in PROVIDER_TYPES:
                    errors.append(f"{path}.provider.type must be one of {sorted(PROVIDER_TYPES)}")
                if provider.get("command") not in PROVIDER_COMMANDS:
                    errors.append(f"{path}.provider.command must be one of {sorted(PROVIDER_COMMANDS)}")
                provider_type = provider.get("type")
                providers = provider.get("providers")
                if provider_type == "mco":
                    if "selection" in provider:
                        errors.append(f"{path}.provider.selection is only valid for swarm-review provider stages")
                    if not _is_str_list(providers) or not (1 <= len(providers) <= 5):
                        errors.append(f"{path}.provider.providers must be an array of 1..5 provider names")
                    else:
                        unknown_mco = sorted(set(providers) - MCO_PROVIDERS)
                        if unknown_mco:
                            errors.append(f"{path}.provider.providers contains unsupported MCO provider(s): {', '.join(unknown_mco)}")
                elif provider_type == "swarm-review":
                    selection = provider.get("selection", "auto")
                    if selection not in REVIEW_PROVIDER_SELECTIONS:
                        errors.append(f"{path}.provider.selection must be one of {sorted(REVIEW_PROVIDER_SELECTIONS)}")
                    if pipeline.get("origin") == "stock" and providers is not None:
                        errors.append(f"{path}.provider.providers is not allowed in stock swarm-review pipelines")
                    if selection in {"auto", "off"} and providers is not None:
                        errors.append(f"{path}.provider.providers is only valid when selection is explicit")
                    if selection == "explicit":
                        if not _is_str_list(providers) or not (1 <= len(providers) <= 16):
                            errors.append(f"{path}.provider.providers must be an array of 1..16 provider names for explicit selection")
                        else:
                            invalid_review = sorted(
                                name for name in providers if not name or "/" in name or "\\" in name or name.startswith(".")
                            )
                            if invalid_review:
                                errors.append(f"{path}.provider.providers contains invalid provider id(s): {', '.join(invalid_review)}")
                    max_parallel = provider.get("max_parallel")
                    if max_parallel is not None and (not isinstance(max_parallel, int) or not (1 <= max_parallel <= 32)):
                        errors.append(f"{path}.provider.max_parallel must be an integer from 1 to 32")
                if "mode" in provider and provider.get("mode") not in PROVIDER_MODES:
                    errors.append(f"{path}.provider.mode must be one of {sorted(PROVIDER_MODES)}")
                if "strict_contract" in provider and not isinstance(provider.get("strict_contract"), bool):
                    errors.append(f"{path}.provider.strict_contract must be a boolean")
                if "output" in provider and provider.get("output") not in PROVIDER_OUTPUTS:
                    errors.append(f"{path}.provider.output must be one of {sorted(PROVIDER_OUTPUTS)}")
                if "memory" in provider and not isinstance(provider.get("memory"), bool):
                    errors.append(f"{path}.provider.memory must be a boolean")
                if provider.get("memory") is True:
                    errors.append(f"{path}.provider.memory=true is not allowed for experimental provider stages")
                timeout = provider.get("timeout_seconds")
                if not isinstance(timeout, int) or not (1 <= timeout <= 86400):
                    errors.append(f"{path}.provider.timeout_seconds must be an integer from 1 to 86400")
            if "merge" in stage:
                errors.append(f"{path}: provider stages cannot define merge; use a downstream Claude-backed stage")
        if "merge" in stage:
            merge = stage["merge"]
            if not isinstance(merge, Mapping):
                errors.append(f"{path}.merge must be an object")
            else:
                unknown_merge = sorted(set(merge.keys()) - MERGE_KEYS)
                if "lens" in merge:
                    errors.append(f"{path}.merge.lens is not supported; merge schema has no variant or lens slot")
                    unknown_merge = [key for key in unknown_merge if key != "lens"]
                if unknown_merge:
                    errors.append(f"{path}.merge: unknown keys: {', '.join(unknown_merge)}")
                if merge.get("strategy") not in MERGE_STRATEGIES:
                    errors.append(f"{path}.merge.strategy must be synthesize or vote")
                if merge.get("strategy") == "synthesize" and not isinstance(merge.get("agent"), str):
                    errors.append(f"{path}.merge.agent is required for synthesize")
        tolerance = stage.get("failure_tolerance", {"mode": "strict"})
        if not isinstance(tolerance, Mapping):
            errors.append(f"{path}.failure_tolerance must be a structured object")
        else:
            mode = tolerance.get("mode", "strict")
            if mode not in TOLERANCE_MODES:
                errors.append(f"{path}.failure_tolerance.mode must be one of {sorted(TOLERANCE_MODES)}")
            if mode == "quorum":
                min_success = tolerance.get("min_success")
                if isinstance(stage.get("fan_out"), Mapping):
                    count = stage["fan_out"].get("count", 1)
                else:
                    count = _provider_branch_count(stage)
                if not isinstance(min_success, int) or not (1 <= min_success <= count):
                    errors.append(f"{path}.failure_tolerance.min_success must be 1..stage branch count for quorum")
            elif "min_success" in tolerance:
                errors.append(f"{path}.failure_tolerance.min_success is only valid for quorum")

    for idx, stage in enumerate(stages):
        for dep in stage.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"pipeline.stages[{idx}].depends_on references unknown stage {dep}")
    return errors


def schema_lint_work_units(
    artifact: Mapping[str, Any],
    *,
    max_writer_tool_calls: int | None = None,
    max_writer_output_bytes: int | None = None,
) -> LintResult:
    errors: list[str] = []
    warnings: list[str] = []
    unknown = sorted(set(artifact.keys()) - WORK_UNIT_TOP_KEYS)
    if unknown:
        errors.append(f"work_units: unknown top-level keys: {', '.join(unknown)}")
    schema_version = artifact.get("schema_version")
    if schema_version not in {1, 2}:
        errors.append("work_units: schema_version must be 1 or 2")
    for key in ("plan_path", "bd_epic_id"):
        if key in artifact and artifact[key] is not None and not isinstance(artifact[key], str):
            errors.append(f"work_units: {key} must be a string or null")

    units = artifact.get("work_units")
    if not isinstance(units, list) or not units:
        errors.append("work_units: work_units must be a non-empty array")
        return LintResult(errors, warnings)

    ids: set[str] = set()
    for idx, unit in enumerate(units):
        path = f"work_units.work_units[{idx}]"
        if not isinstance(unit, Mapping):
            errors.append(f"{path}: unit must be an object")
            continue
        unknown_unit = sorted(set(unit.keys()) - WORK_UNIT_KEYS)
        if unknown_unit:
            errors.append(f"{path}: unknown keys: {', '.join(unknown_unit)}")
        required = WORK_UNIT_V1_REQUIRED_KEYS if schema_version == 1 else WORK_UNIT_V2_REQUIRED_KEYS
        missing = sorted(required - set(unit.keys()))
        if schema_version == 2 and "files" not in unit and "allowed_files" not in unit:
            missing.append("allowed_files")
        if missing:
            errors.append(f"{path}: missing required keys: {', '.join(missing)}")

        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id:
            errors.append(f"{path}.id must be a non-empty string")
        elif unit_id in ids:
            errors.append(f"{path}.id duplicates work-unit id {unit_id}")
        else:
            ids.add(unit_id)

        if not _is_str_list(unit.get("depends_on")):
            errors.append(f"{path}.depends_on must be an array of work-unit ids")
        if schema_version == 1:
            if not _is_str_list(unit.get("files")):
                errors.append(f"{path}.files must be an array of strings")
            elif "files" in unit:
                warnings.append(
                    "work_units: schema_version 1 uses legacy files; run `swarm work-units migrate <path> --in-place` to upgrade"
                )
        else:
            has_files = "files" in unit
            has_allowed = "allowed_files" in unit
            if has_files and has_allowed:
                errors.append(f"{path}: exactly one of files or allowed_files is allowed for schema_version 2")
            elif has_files:
                if not _is_str_list(unit.get("files")):
                    errors.append(f"{path}.files must be an array of strings")
                warnings.append(f"{path}.files is a legacy alias; run `swarm work-units migrate <path> --in-place`")
            elif not _is_str_list(unit.get("allowed_files")):
                errors.append(f"{path}.allowed_files must be an array of strings")
            for key in ("context_files", "blocked_files", "validation_commands", "expected_results", "risk_tags"):
                if not _is_str_list(unit.get(key)):
                    errors.append(f"{path}.{key} must be an array of strings")
            if not isinstance(unit.get("title"), str) or not unit.get("title"):
                errors.append(f"{path}.title must be a non-empty string")
            if not isinstance(unit.get("goal"), str):
                errors.append(f"{path}.goal must be a string")
            if not isinstance(unit.get("handoff_notes"), str):
                errors.append(f"{path}.handoff_notes must be a string")
            if unit.get("failure_reason") not in WORK_UNIT_FAILURE_REASONS:
                errors.append(f"{path}.failure_reason must be one of {sorted(v for v in WORK_UNIT_FAILURE_REASONS if v is not None)} or null")
            if "mem_prime" in unit and not isinstance(unit.get("mem_prime"), bool):
                errors.append(f"{path}.mem_prime must be a boolean")
        if not _is_str_list(unit.get("acceptance_criteria")):
            errors.append(f"{path}.acceptance_criteria must be an array of strings")
        elif schema_version == 2 and not unit.get("acceptance_criteria"):
            errors.append(f"{path}.acceptance_criteria must not be empty")
        for key in ("beads_id", "worktree_branch"):
            if unit.get(key) is not None and not isinstance(unit.get(key), str):
                errors.append(f"{path}.{key} must be a string or null")
        if unit.get("status") not in WORK_UNIT_STATUSES:
            errors.append(f"{path}.status must be one of {sorted(WORK_UNIT_STATUSES)}")
        for key in ("retry_count", "handoff_count"):
            value = unit.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"{path}.{key} must be a non-negative integer")
        if schema_version == 2:
            allowed = _unit_allowed_files(unit)
            blocked = unit.get("blocked_files") if isinstance(unit.get("blocked_files"), list) else []
            errors.extend(_file_scope_errors(path, allowed, blocked))
            if _requires_observable_validation(unit) and not unit.get("validation_commands"):
                warnings.append(f"{path}.validation_commands is empty despite observable acceptance criteria")

    for idx, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            continue
        for dep in unit.get("depends_on") or []:
            if isinstance(dep, str) and dep not in ids:
                errors.append(f"work_units.work_units[{idx}].depends_on references unknown work unit {dep}")

    if schema_version == 2 and not errors:
        errors.extend(_parallel_overlap_errors(units))
        from .budget import DEFAULT_MAX_WRITER_OUTPUT_BYTES, DEFAULT_MAX_WRITER_TOOL_CALLS, budget_lint_errors

        max_calls = max_writer_tool_calls if max_writer_tool_calls is not None else DEFAULT_MAX_WRITER_TOOL_CALLS
        max_bytes = max_writer_output_bytes if max_writer_output_bytes is not None else DEFAULT_MAX_WRITER_OUTPUT_BYTES
        for unit in units:
            if isinstance(unit, Mapping):
                errors.extend(budget_lint_errors(unit, max_writer_tool_calls=max_calls, max_writer_output_bytes=max_bytes))

    if not errors:
        from .work_units import topological_work_unit_layers

        try:
            topological_work_unit_layers(artifact)
        except ValueError as exc:
            errors.append(str(exc))
    return LintResult(errors, warnings)


def blocked_file_violations(changed_files: list[str], blocked_files: list[str]) -> list[str]:
    """Return changed paths that match a blocked file glob."""

    violations: list[str] = []
    for changed in changed_files:
        if any(_glob_matches(pattern, changed) for pattern in blocked_files):
            violations.append(changed)
    return sorted(set(violations))


def unit_blocked_file_violations(unit: Mapping[str, Any], changed_files: list[str]) -> list[str]:
    blocked = unit.get("blocked_files")
    patterns = [item for item in blocked if isinstance(item, str)] if isinstance(blocked, list) else []
    return blocked_file_violations(changed_files, patterns)


def _unit_allowed_files(unit: Mapping[str, Any]) -> list[str]:
    value = unit.get("allowed_files", unit.get("files"))
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _file_scope_errors(path: str, allowed: list[str], blocked: list[str]) -> list[str]:
    errors: list[str] = []
    for pattern in allowed:
        if _is_unbounded_glob(pattern):
            errors.append(f"{path}.allowed_files contains unbounded glob {pattern!r}")
    for pattern in blocked:
        if not isinstance(pattern, str):
            continue
        if any(_patterns_overlap(pattern, allowed_pattern) for allowed_pattern in allowed):
            errors.append(f"{path}.blocked_files overlaps allowed_files pattern {pattern!r}")
    return errors


def _is_unbounded_glob(pattern: str) -> bool:
    stripped = pattern.strip()
    if stripped in {"*", "**", "**/*", "./**", "./**/*"}:
        return True
    if stripped.startswith("**"):
        return True
    return False


def _parallel_overlap_errors(units: list[Any]) -> list[str]:
    typed_units = [unit for unit in units if isinstance(unit, Mapping) and isinstance(unit.get("id"), str)]
    ancestors = _dependency_ancestors(typed_units)
    errors: list[str] = []
    for idx, left in enumerate(typed_units):
        left_id = str(left["id"])
        for right in typed_units[idx + 1 :]:
            right_id = str(right["id"])
            if right_id in ancestors.get(left_id, set()) or left_id in ancestors.get(right_id, set()):
                continue
            overlap = _overlap_patterns(_unit_allowed_files(left), _unit_allowed_files(right))
            if overlap:
                errors.append(f"work_units: parallel units {left_id} and {right_id} have overlapping allowed_files: {', '.join(overlap)}")
    return errors


def _dependency_ancestors(units: list[Mapping[str, Any]]) -> dict[str, set[str]]:
    deps = {
        str(unit["id"]): {dep for dep in unit.get("depends_on", []) if isinstance(dep, str)}
        for unit in units
    }
    ancestors: dict[str, set[str]] = {unit_id: set() for unit_id in deps}
    changed = True
    while changed:
        changed = False
        for unit_id, direct_deps in deps.items():
            before = len(ancestors[unit_id])
            ancestors[unit_id].update(direct_deps)
            for dep in list(direct_deps):
                ancestors[unit_id].update(ancestors.get(dep, set()))
            changed = changed or len(ancestors[unit_id]) != before
    return ancestors


def _overlap_patterns(left: list[str], right: list[str]) -> list[str]:
    overlaps: list[str] = []
    for a in left:
        for b in right:
            if _patterns_overlap(a, b):
                overlaps.append(f"{a}<->{b}")
    return overlaps


def _patterns_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    left_prefix = _literal_prefix(left)
    right_prefix = _literal_prefix(right)
    if left_prefix and right_prefix and (left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix)):
        return True
    return _glob_matches(left, right) or _glob_matches(right, left)


def _literal_prefix(pattern: str) -> str:
    specials = [idx for idx in (pattern.find("*"), pattern.find("?"), pattern.find("[")) if idx >= 0]
    if not specials:
        return pattern
    return pattern[: min(specials)]


def _glob_matches(pattern: str, path: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).as_posix(), pattern)


def _requires_observable_validation(unit: Mapping[str, Any]) -> bool:
    criteria = " ".join(item for item in unit.get("acceptance_criteria", []) if isinstance(item, str)).lower()
    return any(word in criteria for word in ("test", "command", "cli", "output", "validates", "runs", "exits", "schema"))


def validate_preset_and_pipeline(
    preset_name: str,
    plan_path: str | None = None,
    include_budget: bool = False,
) -> tuple[ValidationResult, dict[str, Any], dict[str, Any], Path]:
    result = ValidationResult()
    preset_item = find_preset(preset_name)
    if preset_item is None:
        result.add(f"preset not found: {preset_name}")
        return result, {}, {}, Path()
    try:
        preset = load_preset(preset_item.path)
    except Exception as exc:
        result.add(f"preset parse failed: {exc}")
        return result, {}, {}, preset_item.path
    result, pipeline = validate_preset_mapping(preset, preset_name, plan_path, include_budget)
    return result, preset, pipeline, preset_item.path


def validate_preset_mapping(
    preset: Mapping[str, Any],
    preset_name: str | None = None,
    plan_path: str | None = None,
    include_budget: bool = False,
) -> tuple[ValidationResult, dict[str, Any]]:
    pipeline_item = find_pipeline(str(preset.get("pipeline", "")))
    if pipeline_item is None:
        result = ValidationResult()
        result.errors.extend(schema_lint_preset(preset))
        result.add(f"pipeline not found: {preset.get('pipeline')}")
        return result, {}
    try:
        pipeline = load_pipeline(pipeline_item.path)
    except Exception as exc:
        result = ValidationResult()
        result.errors.extend(schema_lint_preset(preset))
        result.add(f"pipeline parse failed: {exc}")
        return result, {}
    result = validate_preset_pipeline_mappings(preset, pipeline, preset_name, plan_path, include_budget)
    return result, pipeline


def validate_preset_pipeline_mappings(
    preset: Mapping[str, Any],
    pipeline: Mapping[str, Any],
    preset_name: str | None = None,
    plan_path: str | None = None,
    include_budget: bool = False,
) -> ValidationResult:
    result = ValidationResult()
    result.errors.extend(schema_lint_preset(preset))
    result.errors.extend(schema_lint_pipeline(pipeline))
    result.errors.extend(role_existence_errors(pipeline))
    result.errors.extend(variant_existence_errors(pipeline))
    result.errors.extend(route_resolution_errors(pipeline, preset_name, preset))
    result.errors.extend(invariant_errors(pipeline, preset_name, preset))
    try:
        topological_layers(pipeline)
    except ValueError as exc:
        result.add(str(exc))

    if include_budget:
        try:
            result.budget = budget_preview(preset, pipeline, plan_path)
            result.errors.extend(result.budget.exceeds)
        except Exception as exc:
            result.add(f"budget preview failed: {exc}")
    return result


def role_existence_errors(pipeline: Mapping[str, Any]) -> list[str]:
    return [f"role file missing for {role}" for role in sorted(set(_all_roles(pipeline))) if not _role_exists(role)]


def variant_existence_errors(pipeline: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        stage_id = stage.get("id", "<unknown>")
        for idx, agent in enumerate(stage.get("agents") or []):
            if not isinstance(agent, Mapping):
                continue
            role = agent.get("role")
            lens_id = agent.get("lens")
            if not isinstance(role, str) or not isinstance(lens_id, str):
                continue
            lens = get_lens(lens_id)
            if lens is None:
                continue
            variant_name = lens.variant_for_role(role)
            variant_file = lens.variant_file_for_role(role)
            if variant_name is None or variant_file is None:
                errors.append(f"stage {stage_id} agents[{idx}] lens {lens_id} has no prompt variant mapping for {role}")
            elif not variant_file.is_file():
                errors.append(f"variant file missing for stage {stage_id} agents[{idx}] lens {role}/{lens_id}: {variant_file}")
        fan = stage.get("fan_out")
        if not isinstance(fan, Mapping) or fan.get("variant") != "prompt_variants":
            continue
        role = fan.get("role")
        if not isinstance(role, str):
            continue
        for variant in fan.get("variants") or []:
            path = REPO_ROOT / "roles" / role / "variants" / f"{variant}.md"
            if not path.is_file():
                errors.append(f"variant file missing for {role}/{variant}: {path}")
    return errors


def route_resolution_errors(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    resolver = BackendResolver(preset_name=preset_name, preset_data=preset)
    for stage in pipeline.get("stages") or []:
        stage_id = stage.get("id", "<unknown>")
        for agent in stage.get("agents") or []:
            if not isinstance(agent, Mapping):
                continue
            role = agent.get("role")
            if not isinstance(role, str):
                continue
            override = agent.get("route")
            if override is None and {"backend", "model", "effort"} <= set(agent.keys()):
                override = agent
            if override is None:
                continue
            try:
                resolver.resolve(role, override=override)
            except Exception as exc:
                errors.append(f"route resolution failed for stage {stage_id} role {role}: {exc}")

        fan = stage.get("fan_out")
        if not isinstance(fan, Mapping) or fan.get("variant") != "models":
            continue
        role = fan.get("role")
        if not isinstance(role, str):
            continue
        routes = fan.get("routes")
        if not isinstance(routes, list):
            continue
        for idx, route in enumerate(routes):
            try:
                resolver.resolve(role, override=route)
            except Exception as exc:
                errors.append(f"route resolution failed for stage {stage_id} fan_out.routes[{idx}]: {exc}")
    return errors


def invariant_errors(
    pipeline: Mapping[str, Any],
    preset_name: str | None,
    preset: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    resolver = BackendResolver(preset_name=preset_name, preset_data=preset)
    try:
        if not resolver.is_claude_backed("orchestrator", "hard"):
            errors.append("invariant: orchestrator must resolve to a Claude backend")
    except Exception as exc:
        errors.append(f"invariant: orchestrator route resolution failed: {exc}")
    try:
        if not resolver.is_claude_backed("agent-code-synthesizer", "hard"):
            errors.append("invariant: agent-code-synthesizer must resolve to a Claude backend")
    except Exception as exc:
        errors.append(f"invariant: synthesizer route resolution failed: {exc}")
    for stage in pipeline.get("stages") or []:
        stage_id = stage.get("id", "<unknown>")
        for agent_entry in stage.get("agents") or []:
            if not isinstance(agent_entry, Mapping):
                continue
            role = agent_entry.get("role")
            if role not in {"orchestrator", "agent-code-synthesizer"}:
                continue
            override = agent_entry.get("route")
            if override is None and {"backend", "model", "effort"} <= set(agent_entry):
                override = agent_entry
            try:
                if not resolver.is_claude_backed(role, "hard", override=override):
                    errors.append(f"invariant: stage {stage_id} role {role} must resolve to a Claude backend")
            except Exception as exc:
                errors.append(f"invariant: stage {stage_id} role {role} route resolution failed: {exc}")
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and merge.get("strategy") == "synthesize":
            agent = merge.get("agent")
            if isinstance(agent, str):
                try:
                    if not resolver.is_claude_backed(agent, "hard"):
                        errors.append(f"invariant: synthesize merge agent {agent} must resolve to a Claude backend")
                except Exception as exc:
                    errors.append(f"invariant: merge agent {agent} route resolution failed: {exc}")
    return errors
