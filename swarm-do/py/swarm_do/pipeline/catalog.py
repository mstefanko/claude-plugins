"""Curated pipeline module and lens catalog.

The catalog is intentionally plain Python data. Pipeline YAML remains the
runtime source of truth; these specs describe which edits the composer can
offer safely before writing validated YAML/TOML artifacts.
"""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT


@dataclasses.dataclass(frozen=True)
class OutputContract:
    sections: tuple[str, ...]
    allowed_tags: Mapping[str, tuple[str, ...]]
    schema_rule: str


@dataclasses.dataclass(frozen=True)
class LensSpec:
    lens_id: str
    label: str
    category: str
    description: str
    stability: str
    roles: tuple[str, ...]
    stage_kinds: tuple[str, ...]
    execution_mode: str
    variant_name: str | None
    variant_path: str | None
    output_contract: OutputContract
    merge_expectation: str
    role_variants: Mapping[str, tuple[str, str]] = dataclasses.field(default_factory=dict)
    role_output_contracts: Mapping[str, OutputContract] = dataclasses.field(default_factory=dict)
    conflicts: tuple[str, ...] = ()
    stacking_policy: str = "one lens per branch; no stacked prompt overlays in v1"
    safety_notes: tuple[str, ...] = ()
    route_constraint: str | None = None
    telemetry_tags: tuple[str, ...] = ()

    @property
    def variant_file(self) -> Path | None:
        if self.variant_path is None:
            return None
        return REPO_ROOT / self.variant_path

    def variant_for_role(self, role: str) -> str | None:
        role_variant = self.role_variants.get(role)
        if role_variant is not None:
            return role_variant[0]
        if role in self.roles:
            return self.variant_name
        return None

    def variant_file_for_role(self, role: str) -> Path | None:
        role_variant = self.role_variants.get(role)
        if role_variant is not None:
            return REPO_ROOT / role_variant[1]
        if role in self.roles:
            return self.variant_file
        return None

    def output_contract_for_role(self, role: str) -> OutputContract:
        return self.role_output_contracts.get(role, self.output_contract)

    def supports(self, *, role: str, stage_kind: str) -> bool:
        return role in self.roles and stage_kind in self.stage_kinds

    @property
    def supports_single_agent(self) -> bool:
        return "agents" in self.stage_kinds


@dataclasses.dataclass(frozen=True)
class RouteLensSpec:
    lens_id: str
    label: str
    description: str
    scope: str
    runtime_primitive: str


@dataclasses.dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    label: str
    description: str
    category: str
    stage_template: Mapping[str, Any]
    allowed_after: tuple[str, ...] = ()
    allowed_before: tuple[str, ...] = ()
    required_upstream: tuple[str, ...] = ()
    required_downstream: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("read-only",)
    preview_only: bool = False
    requires_command_profile: bool = False
    requires_provider_doctor: bool = False
    experimental: bool = False

    def instantiate_stage(self, *, stage_id: str | None = None) -> dict[str, Any]:
        stage = copy.deepcopy(dict(self.stage_template))
        if stage_id is not None:
            stage["id"] = stage_id
        return stage


@dataclasses.dataclass(frozen=True)
class PipelineProfileSpec:
    profile_id: str
    label: str
    description: str
    command_name: str | None
    terminal_behavior: str
    output_only: bool
    preview_only: bool
    requires_command_profile: bool
    pipeline_names: tuple[str, ...] = ()
    preset_names: tuple[str, ...] = ()


AGENTS_LENS_STACKING_ERROR = "lens stacking is disabled for normal agents stages; use singular lens"


ANALYSIS_CONTRACT = OutputContract(
    sections=(
        "Assumptions",
        "Recommended Approach",
        "Why Not",
        "Work Breakdown",
        "Risks",
        "Out of Scope",
        "Test Coverage Needed",
        "Bounded Work Units",
    ),
    allowed_tags={
        "Risks": (
            "[ARCH-RISK]",
            "[API-BREAK]",
            "[API-COMPAT]",
            "[DATA-MIGRATION]",
            "[STATE-CORRUPTION]",
            "[INDEX]",
            "[CROSS-RUN-COMPARABILITY]",
        ),
    },
    schema_rule="Preserve the agent-analysis output schema, required sections, and downstream handoff format.",
)


RESEARCH_CONTRACT = OutputContract(
    sections=(
        "Relevant Files",
        "Existing Patterns",
        "Constraints",
        "Prior Solutions",
        "Raw Notes",
        "Sources",
    ),
    allowed_tags={
        "Relevant Files": (
            "[ENTRY-POINT]",
            "[CONFIG]",
            "[HOT-PATH]",
            "[TEST]",
            "[FIXTURE]",
            "[GENERATED]",
        ),
        "Prior Solutions": ("[REUSE]", "[ADAPT]", "[REJECTED-EARLIER]", "[NONE]"),
        "Constraints": (
            "[REGRESSION-RISK]",
            "[CONTRACT-CONSTRAINT]",
            "[ENVIRONMENTAL]",
            "[CULTURAL]",
        ),
        "Raw Notes": (
            "[REGRESSION-RISK]",
            "[CONTRACT-CONSTRAINT]",
            "[ENVIRONMENTAL]",
            "[CULTURAL]",
        ),
    },
    schema_rule="Preserve the agent-research output schema, required sections, and COMPLETE | NEEDS_INPUT status vocabulary.",
)


REVIEW_CONTRACT = OutputContract(
    sections=(
        "Verdict",
        "Checks Run",
        "Issues Found",
        "Production Risk",
    ),
    allowed_tags={
        "Issues Found": (
            "[LOGIC]",
            "[CONTRACT]",
            "[INVARIANT]",
            "[STATE-MACHINE]",
            "[API-BREAK]",
            "[API-COMPAT]",
            "[SPOOF]",
            "[TAMPER]",
            "[REPUDIATION]",
            "[INFO-DISCLOSURE]",
            "[DOS]",
            "[ELEVATION]",
            "[N+1]",
            "[O-N2]",
            "[ALLOC]",
            "[BLOCKING-IO]",
            "[CONTENTION]",
            "[NULL]",
            "[OFF-BY-ONE]",
            "[BOUNDARY]",
            "[EMPTY]",
            "[OVERFLOW]",
            "[TIME-ZONE]",
            "[UNICODE]",
        ),
    },
    schema_rule="Preserve the agent-review output schema, section names, no-edit rule, and APPROVED | NEEDS_CHANGES verdict vocabulary.",
)


_PROMPT_LENSES: tuple[LensSpec, ...] = (
    LensSpec(
        lens_id="architecture-risk",
        label="Architecture Risk",
        category="task-rubric",
        description=(
            "Bias analysis toward coupling, reversibility, migration risk, "
            "and failure modes that would be expensive to unwind."
        ),
        stability="stock",
        roles=("agent-analysis",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="explorer-a",
        variant_path="roles/agent-analysis/variants/explorer-a.md",
        output_contract=ANALYSIS_CONTRACT,
        merge_expectation=(
            "agent-analysis-judge should prefer concrete architecture-risk "
            "inventories and surface reversibility disagreements."
        ),
        telemetry_tags=(
            "category=task-rubric",
            "axis=architecture",
            "host=agent-analysis",
            "mode=fan_out",
            "mode=single_agent",
            "signal=reversibility-density",
        ),
    ),
    LensSpec(
        lens_id="api-contract",
        label="API Contract Stability",
        category="task-rubric",
        description=(
            "Bias analysis toward public interfaces, CLI flags, schemas, "
            "file formats, environment variables, and compatibility promises."
        ),
        stability="stock",
        roles=("agent-analysis", "agent-review"),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="explorer-b",
        variant_path="roles/agent-analysis/variants/explorer-b.md",
        output_contract=ANALYSIS_CONTRACT,
        merge_expectation=(
            "agent-analysis-judge should prefer concrete break vectors with "
            "file or schema citations and surface compatibility disagreements."
        ),
        role_variants={
            "agent-review": ("api-contract", "roles/agent-review/variants/api-contract.md"),
        },
        role_output_contracts={"agent-review": REVIEW_CONTRACT},
        telemetry_tags=(
            "category=task-rubric",
            "axis=api-compat",
            "host=agent-analysis",
            "host=agent-review",
            "mode=fan_out",
            "mode=single_agent",
            "signal=break-vector-density",
        ),
    ),
    LensSpec(
        lens_id="state-data",
        label="State & Data Implications",
        category="task-rubric",
        description=(
            "Bias analysis toward persisted state, append-only ledgers, "
            "hashing, indexes, migrations, and cross-run comparability."
        ),
        stability="stock",
        roles=("agent-analysis",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="explorer-c",
        variant_path="roles/agent-analysis/variants/explorer-c.md",
        output_contract=ANALYSIS_CONTRACT,
        merge_expectation=(
            "agent-analysis-judge should prefer migration, backfill, hash, "
            "and comparability plans concrete enough for a writer to implement."
        ),
        telemetry_tags=(
            "category=task-rubric",
            "axis=state-data",
            "host=agent-analysis",
            "mode=fan_out",
            "mode=single_agent",
            "signal=migration-density",
        ),
    ),
    LensSpec(
        lens_id="security-threat-model",
        label="Security Threat Model",
        category="task-rubric",
        description=(
            "Bias analysis or review toward trust boundaries, untrusted input, "
            "secret handling, authorization, injection, and security-critical state."
        ),
        stability="stock",
        roles=("agent-analysis", "agent-review"),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="security-threat-model",
        variant_path="roles/agent-analysis/variants/security-threat-model.md",
        output_contract=ANALYSIS_CONTRACT,
        merge_expectation=(
            "Merge should prefer concrete trust-boundary evidence and attacker-input "
            "examples, surfacing reachability disagreements instead of smoothing them over."
        ),
        role_variants={
            "agent-review": ("security-threat-model", "roles/agent-review/variants/security-threat-model.md"),
        },
        role_output_contracts={"agent-review": REVIEW_CONTRACT},
        safety_notes=(
            "security-sensitive",
            "Threat modeling and review notes only; do not generate proof-of-concept exploits or bypass no-edit constraints.",
        ),
        telemetry_tags=(
            "category=task-rubric",
            "axis=security",
            "host=agent-analysis",
            "host=agent-review",
            "mode=fan_out",
            "mode=single_agent",
            "signal=stride-coverage",
            "signal=trust-boundary-density",
        ),
    ),
    LensSpec(
        lens_id="prior-art-search",
        label="Prior Art Search",
        category="scoping",
        description="Bias research toward prior commits, ADRs, docs, memory observations, and external precedent.",
        stability="stock",
        roles=("agent-research",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="prior-art-search",
        variant_path="roles/agent-research/variants/prior-art-search.md",
        output_contract=RESEARCH_CONTRACT,
        merge_expectation=(
            "agent-research-merge should consolidate prior solutions into cross-cutting "
            "patterns and surface duplicate or rejected prior attempts."
        ),
        telemetry_tags=(
            "category=scoping",
            "axis=prior-art",
            "host=agent-research",
            "mode=fan_out",
            "mode=single_agent",
            "signal=duplicate-detection",
        ),
    ),
    LensSpec(
        lens_id="codebase-map",
        label="Codebase Map",
        category="scoping",
        description="Bias research toward exhaustive affected-surface mapping and file roles.",
        stability="stock",
        roles=("agent-research",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="codebase-map",
        variant_path="roles/agent-research/variants/codebase-map.md",
        output_contract=RESEARCH_CONTRACT,
        merge_expectation=(
            "agent-research-merge should deduplicate file citations, preserve file-role "
            "classifications, and flag files that siblings classify differently."
        ),
        telemetry_tags=(
            "category=scoping",
            "axis=scope",
            "host=agent-research",
            "mode=fan_out",
            "mode=single_agent",
            "signal=file-role-coverage",
        ),
    ),
    LensSpec(
        lens_id="risk-discovery",
        label="Risk Discovery",
        category="scoping",
        description="Bias research toward regression, environmental, contract, and prior-attempt risks.",
        stability="stock",
        roles=("agent-research",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="risk-discovery",
        variant_path="roles/agent-research/variants/risk-discovery.md",
        output_contract=RESEARCH_CONTRACT,
        merge_expectation=(
            "agent-research-merge should lift risk flags into cross-cutting concerns "
            "and preserve conflicting risk assessments."
        ),
        telemetry_tags=(
            "category=scoping",
            "axis=risk-surface",
            "host=agent-research",
            "mode=fan_out",
            "mode=single_agent",
            "signal=constraint-density",
        ),
    ),
    LensSpec(
        lens_id="correctness-rubric",
        label="Correctness Rubric",
        category="task-rubric",
        description="Bias review toward logic, invariants, state machines, and behavioral contracts.",
        stability="stock",
        roles=("agent-review",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="correctness-rubric",
        variant_path="roles/agent-review/variants/correctness-rubric.md",
        output_contract=REVIEW_CONTRACT,
        merge_expectation=(
            "Review synthesis should prefer concrete behavioral failures with file:line "
            "evidence and preserve disagreements about invariant boundaries."
        ),
        telemetry_tags=(
            "category=task-rubric",
            "axis=correctness",
            "host=agent-review",
            "mode=fan_out",
            "mode=single_agent",
            "signal=invariant-density",
        ),
    ),
    LensSpec(
        lens_id="performance-review",
        label="Performance Review",
        category="task-rubric",
        description="Bias review toward hot paths, asymptotic behavior, blocking IO, allocations, and contention.",
        stability="stock",
        roles=("agent-review",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="performance-review",
        variant_path="roles/agent-review/variants/performance-review.md",
        output_contract=REVIEW_CONTRACT,
        merge_expectation=(
            "Review synthesis should prefer findings with concrete input sizes, call "
            "frequencies, or load triggers over abstract complexity concerns."
        ),
        telemetry_tags=(
            "category=task-rubric",
            "axis=performance",
            "host=agent-review",
            "mode=fan_out",
            "mode=single_agent",
            "signal=trigger-density",
        ),
    ),
    LensSpec(
        lens_id="edge-case-review",
        label="Edge Case Review",
        category="task-rubric",
        description="Bias review toward null, empty, boundary, overflow, timezone, unicode, and concurrency edges.",
        stability="stock",
        roles=("agent-review",),
        stage_kinds=("fan_out", "agents"),
        execution_mode="fan_out_or_single_agent",
        variant_name="edge-case-review",
        variant_path="roles/agent-review/variants/edge-case-review.md",
        output_contract=REVIEW_CONTRACT,
        merge_expectation=(
            "Review synthesis should prefer concrete failing inputs over abstract edge-class labels."
        ),
        telemetry_tags=(
            "category=task-rubric",
            "axis=edge-cases",
            "host=agent-review",
            "mode=fan_out",
            "mode=single_agent",
            "signal=concrete-input-density",
        ),
    ),
)


_ROUTE_LENSES: tuple[RouteLensSpec, ...] = (
    RouteLensSpec(
        lens_id="preset-role-route",
        label="Preset Role Route",
        description="Override a role or role/complexity route in preset routing.",
        scope="preset",
        runtime_primitive="preset.routing",
    ),
    RouteLensSpec(
        lens_id="stage-agent-route",
        label="Stage Agent Route",
        description="Override backend, model, and effort for one inline agents stage entry.",
        scope="agents-stage",
        runtime_primitive="stages[].agents[] backend/model/effort or route",
    ),
    RouteLensSpec(
        lens_id="fan-out-model-routes",
        label="Fan-Out Model Routes",
        description="Use per-branch route objects or named preset routes in a models fan-out.",
        scope="fan_out",
        runtime_primitive="fan_out.variant=models routes[]",
    ),
)


_MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        module_id="research",
        label="Research",
        description="Single research stage that gathers files, constraints, prior solutions, and sources.",
        category="scoping",
        stage_template={"id": "research", "agents": [{"role": "agent-research"}]},
    ),
    ModuleSpec(
        module_id="clarify",
        label="Clarify",
        description="Pre-flight ambiguity and blocker check.",
        category="process",
        stage_template={"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
    ),
    ModuleSpec(
        module_id="analysis",
        label="Analysis",
        description="Single implementation planning stage.",
        category="planning",
        stage_template={"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
    ),
    ModuleSpec(
        module_id="analysis-fan-out",
        label="Analysis Fan-Out",
        description="Prompt-variant analysis fan-out with a Claude-backed synthesis merge.",
        category="planning",
        stage_template={
            "id": "exploration",
            "depends_on": ["research"],
            "fan_out": {
                "role": "agent-analysis",
                "count": 3,
                "variant": "prompt_variants",
                "variants": ["explorer-a", "explorer-b", "explorer-c"],
            },
            "merge": {"strategy": "synthesize", "agent": "agent-analysis-judge"},
            "failure_tolerance": {"mode": "quorum", "min_success": 2},
        },
    ),
    ModuleSpec(
        module_id="writer",
        label="Writer",
        description="Implementation writer stage.",
        category="implementation",
        stage_template={"id": "writer", "depends_on": ["analysis", "clarify"], "agents": [{"role": "agent-writer"}]},
        capabilities=("write-capable",),
    ),
    ModuleSpec(
        module_id="spec-review",
        label="Spec Review",
        description="Review implementation against the planned work breakdown.",
        category="review",
        stage_template={"id": "spec-review", "depends_on": ["writer"], "agents": [{"role": "agent-spec-review"}]},
    ),
    ModuleSpec(
        module_id="review",
        label="Review",
        description="Primary code quality review.",
        category="review",
        stage_template={"id": "review", "depends_on": ["spec-review"], "agents": [{"role": "agent-review"}]},
    ),
    ModuleSpec(
        module_id="docs",
        label="Docs",
        description="Documentation update stage.",
        category="implementation",
        stage_template={"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        capabilities=("write-capable",),
    ),
    ModuleSpec(
        module_id="codex-review",
        label="Codex Review",
        description="Best-effort Codex blocking-issues review lane.",
        category="review",
        stage_template={
            "id": "codex-review",
            "depends_on": ["spec-review"],
            "agents": [{"role": "agent-codex-review", "backend": "codex", "model": "gpt-5.4", "effort": "high"}],
            "failure_tolerance": {"mode": "best-effort"},
        },
    ),
    ModuleSpec(
        module_id="mco-review",
        label="MCO Review",
        description="Experimental read-only MCO evidence provider stage.",
        category="provider",
        stage_template={
            "id": "mco-review",
            "depends_on": ["writer"],
            "provider": {
                "type": "mco",
                "command": "review",
                "providers": ["claude"],
                "mode": "review",
                "strict_contract": True,
                "output": "findings",
                "memory": False,
                "timeout_seconds": 1800,
            },
            "failure_tolerance": {"mode": "best-effort"},
        },
        requires_provider_doctor=True,
        experimental=True,
    ),
    ModuleSpec(
        module_id="provider-review",
        label="Provider Review",
        description="Internal swarm-owned read-only provider evidence stage.",
        category="provider",
        stage_template={
            "id": "provider-review",
            "depends_on": ["writer"],
            "provider": {
                "type": "swarm-review",
                "command": "review",
                "selection": "auto",
                "output": "findings",
                "memory": False,
                "timeout_seconds": 1800,
                "max_parallel": 4,
            },
            "failure_tolerance": {"mode": "best-effort"},
        },
        requires_provider_doctor=True,
        experimental=True,
    ),
)


_IMPLEMENTATION_PROFILE = PipelineProfileSpec(
    profile_id="implementation",
    label="Implementation",
    description="Plan-oriented pipeline that can run through /swarmdaddy:do and may open writer branches and a PR.",
    command_name="/swarmdaddy:do",
    terminal_behavior="implementation handoff with writer/review/doc lanes and a consolidated PR when the run completes",
    output_only=False,
    preview_only=False,
    requires_command_profile=False,
)


_BRAINSTORM_PROFILE = PipelineProfileSpec(
    profile_id="brainstorm",
    label="Brainstorm",
    description="Output-only ideation pipeline that produces a synthesis note without writer branches or a PR.",
    command_name="/swarmdaddy:brainstorm",
    terminal_behavior="synthesis note with directions, tradeoffs, fast checks, and open questions; no writer branch, implementation handoff, or PR",
    output_only=True,
    preview_only=False,
    requires_command_profile=False,
    pipeline_names=("brainstorm",),
    preset_names=("brainstorm",),
)


_RESEARCH_PROFILE = PipelineProfileSpec(
    profile_id="research",
    label="Research",
    description="Output-only research pipeline that produces an evidence memo without writer branches or a PR.",
    command_name="/swarmdaddy:research",
    terminal_behavior="evidence memo or Beads synthesis note; no writer branch, implementation handoff, or PR",
    output_only=True,
    preview_only=False,
    requires_command_profile=False,
    pipeline_names=("research",),
    preset_names=("research",),
)


_DESIGN_PROFILE = PipelineProfileSpec(
    profile_id="design",
    label="Design",
    description="Output-only design pipeline that produces a recommendation and execution-ready plan.",
    command_name="/swarmdaddy:design",
    terminal_behavior="recommendation and execution-ready design note; no writer branch, implementation handoff, or PR",
    output_only=True,
    preview_only=False,
    requires_command_profile=False,
    pipeline_names=("design",),
    preset_names=("design",),
)


_REVIEW_PROFILE = PipelineProfileSpec(
    profile_id="review",
    label="Review",
    description="Output-only review pipeline that produces a findings and evidence summary.",
    command_name="/swarmdaddy:review",
    terminal_behavior="findings/evidence summary with checks, issues, and production risk; no writer branch, implementation handoff, or PR",
    output_only=True,
    preview_only=False,
    requires_command_profile=False,
    pipeline_names=("review",),
    preset_names=("review",),
)


_PREVIEW_ONLY_PROFILE = PipelineProfileSpec(
    profile_id="preview-only",
    label="Preview Only",
    description="Output-only pipeline shape without a command/profile binding yet.",
    command_name=None,
    terminal_behavior="browse, fork, lint, diff, and save only",
    output_only=True,
    preview_only=True,
    requires_command_profile=True,
)


_OUTPUT_PROFILES: tuple[PipelineProfileSpec, ...] = (
    _BRAINSTORM_PROFILE,
    _RESEARCH_PROFILE,
    _DESIGN_PROFILE,
    _REVIEW_PROFILE,
)


def list_modules() -> list[ModuleSpec]:
    return sorted(_MODULES, key=lambda item: item.module_id)


def get_module(module_id: str) -> ModuleSpec | None:
    return next((item for item in _MODULES if item.module_id == module_id), None)


def list_prompt_lenses(*, role: str | None = None, stage_kind: str | None = None) -> list[LensSpec]:
    lenses = list(_PROMPT_LENSES)
    if role is not None:
        lenses = [lens for lens in lenses if role in lens.roles]
    if stage_kind is not None:
        lenses = [lens for lens in lenses if stage_kind in lens.stage_kinds]
    return sorted(lenses, key=lambda item: item.lens_id)


def list_route_lenses() -> list[RouteLensSpec]:
    return sorted(_ROUTE_LENSES, key=lambda item: item.lens_id)


def get_lens(lens_id: str) -> LensSpec | None:
    return next((lens for lens in _PROMPT_LENSES if lens.lens_id == lens_id), None)


def lens_for_variant(role: str, variant_name: str) -> LensSpec | None:
    return next(
        (
            lens
            for lens in _PROMPT_LENSES
            if lens.variant_for_role(role) == variant_name
        ),
        None,
    )


def discover_prompt_variant_files(repo_root: Path = REPO_ROOT) -> dict[str, tuple[str, ...]]:
    variants: dict[str, list[str]] = {}
    roles_dir = repo_root / "roles"
    for path in sorted(roles_dir.glob("*/variants/*.md")):
        role = path.parents[1].name
        variants.setdefault(role, []).append(path.stem)
    return {role: tuple(names) for role, names in sorted(variants.items())}


def explain_lens_incompatibility(lens_id: str, *, role: str, stage_kind: str) -> str | None:
    lens = get_lens(lens_id)
    if lens is None:
        return f"unknown lens: {lens_id}"
    if role not in lens.roles:
        return f"{lens_id} is compatible with {', '.join(lens.roles)}, not {role}"
    if stage_kind not in lens.stage_kinds:
        if stage_kind == "agents":
            return f"{lens_id} cannot target normal agents stages for {role}"
        if stage_kind == "merge":
            return f"{lens_id} cannot target merge.agent in v1 because merge schema has no variant or lens slot"
        if stage_kind == "provider":
            return f"{lens_id} is a prompt lens; provider stages only accept provider evidence modules"
        return f"{lens_id} is not compatible with stage kind {stage_kind}"
    return None


def validate_prompt_lens_selection(
    role: str,
    lens_ids: list[str] | tuple[str, ...],
    *,
    stage_kind: str = "fan_out",
    require_files: bool = True,
) -> list[str]:
    errors: list[str] = []
    if not lens_ids:
        errors.append("at least one lens is required")
    if stage_kind == "agents" and len(lens_ids) > 1:
        errors.append(AGENTS_LENS_STACKING_ERROR)
    seen: set[str] = set()
    selected: list[LensSpec] = []
    for lens_id in lens_ids:
        if lens_id in seen:
            errors.append(f"duplicate lens: {lens_id}")
            continue
        seen.add(lens_id)
        lens = get_lens(lens_id)
        if lens is None:
            errors.append(f"unknown lens: {lens_id}")
            continue
        reason = explain_lens_incompatibility(lens_id, role=role, stage_kind=stage_kind)
        if reason:
            errors.append(reason)
        if lens.variant_for_role(role) is None:
            errors.append(f"{lens_id} has no prompt variant mapping for {role}")
        variant_file = lens.variant_file_for_role(role)
        if require_files and variant_file is not None and not variant_file.is_file():
            errors.append(f"variant file missing for {lens.lens_id}: {variant_file}")
        selected.append(lens)

    selected_ids = {lens.lens_id for lens in selected}
    for lens in selected:
        conflicts = sorted(selected_ids.intersection(lens.conflicts))
        if conflicts:
            errors.append(f"{lens.lens_id} conflicts with {', '.join(conflicts)}")
    return errors


def compile_prompt_variant_fan_out(role: str, lens_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
    errors = validate_prompt_lens_selection(role, lens_ids, stage_kind="fan_out", require_files=True)
    if errors:
        raise ValueError("; ".join(errors))
    variants: list[str] = []
    for lens_id in lens_ids:
        lens = get_lens(lens_id)
        variant_name = lens.variant_for_role(role) if lens is not None else None
        if lens is None or variant_name is None:
            raise ValueError(f"lens has no prompt variant mapping: {lens_id}")
        variants.append(variant_name)
    return {
        "role": role,
        "count": len(variants),
        "variant": "prompt_variants",
        "variants": variants,
    }


def list_pipeline_profiles() -> list[PipelineProfileSpec]:
    return [_IMPLEMENTATION_PROFILE, *_OUTPUT_PROFILES, _PREVIEW_ONLY_PROFILE]


def _named_profile_for(pipeline_name: str, source_name: str | None) -> PipelineProfileSpec | None:
    for profile in _OUTPUT_PROFILES:
        if pipeline_name in profile.pipeline_names or source_name in profile.pipeline_names:
            return profile
    return None


def _pipeline_roles(pipeline: Mapping[str, Any]) -> set[str]:
    roles: set[str] = set()
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        for agent in stage.get("agents") or []:
            if isinstance(agent, Mapping) and isinstance(agent.get("role"), str):
                roles.add(agent["role"])
        fan = stage.get("fan_out")
        if isinstance(fan, Mapping) and isinstance(fan.get("role"), str):
            roles.add(fan["role"])
        merge = stage.get("merge")
        if isinstance(merge, Mapping) and isinstance(merge.get("agent"), str):
            roles.add(merge["agent"])
    return roles


def pipeline_has_writer(pipeline: Mapping[str, Any]) -> bool:
    return "agent-writer" in _pipeline_roles(pipeline)


def pipeline_is_research_only(pipeline: Mapping[str, Any]) -> bool:
    roles = _pipeline_roles(pipeline)
    if not roles or not roles.issubset({"agent-research", "agent-research-merge"}):
        return False
    for stage in pipeline.get("stages") or []:
        if isinstance(stage, Mapping) and "provider" in stage:
            return False
    return True


def pipeline_profile_for(pipeline_name: str, pipeline: Mapping[str, Any]) -> PipelineProfileSpec:
    source = pipeline.get("forked_from") if isinstance(pipeline.get("forked_from"), str) else None
    named_profile = _named_profile_for(pipeline_name, source)
    if named_profile is not None:
        return named_profile
    if pipeline_is_research_only(pipeline):
        return _RESEARCH_PROFILE
    if pipeline_has_writer(pipeline):
        return _IMPLEMENTATION_PROFILE
    return _PREVIEW_ONLY_PROFILE


def pipeline_activation_error(pipeline_name: str, pipeline: Mapping[str, Any]) -> str | None:
    profile = pipeline_profile_for(pipeline_name, pipeline)
    if not profile.preview_only:
        return None
    return (
        f"pipeline {pipeline_name} is preview-only until a command/profile binding exists; "
        f"current profile={profile.profile_id}"
    )
