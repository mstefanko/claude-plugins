"""Recipe catalog for new-preset creation flow (Phase 1).

Pure data + builders. No I/O. No file/TOML/YAML reads at runtime.

Each builder returns Python mappings. The module never references stock
pipelines by name (`pipeline = "<stock-name>"`); every produced preset uses
`origin = "user"` and an inline `pipeline_inline` mapping.

Validation gates:
- ``swarm_do.pipeline.validation.validate_preset_mapping``
- ``swarm_do.pipeline.catalog.pipeline_activation_error``

Design decisions (per analysis ``mstefanko-plugins-fve`` and research
``mstefanko-plugins-bme``):
- Where the plan prose disagrees with the actual ``pipelines/*.yaml``
  fixture (e.g., ``design.yaml`` exploration count is 4 — not 3 as the plan
  prose said), the builder reproduces the **fixture** so drift tests pass.
  The plan prose is the bug; the yaml is ground truth.
- Stock pipeline filenames sometimes collide across recipes (e.g.,
  ``balanced-default``, ``claude-only-diagnostic``, and
  ``codex-only-fallback`` all share ``default.yaml``). ``PresetRecipeSpec``
  carries a private ``_pipeline_fixture`` field so drift tests can resolve
  the right yaml without re-deriving the mapping.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from swarm_do.pipeline.catalog import pipeline_activation_error
from swarm_do.pipeline.validation import validate_preset_mapping

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresetRecipeSpec:
    """A registered preset recipe.

    ``graph_builder`` returns the ``pipeline_inline`` mapping (with
    ``pipeline_version``, ``name``, ``description``, ``stages`` keys).
    ``policy_builder`` returns a mapping of policy keys
    (``review_providers``, ``routing``, ``budget``, ``decompose``,
    ``mem_prime``). Output-only recipes that have no ``review_providers``
    block in the stock fixture should omit that key from policy.
    """

    recipe_id: str
    display_name: str
    intent: str  # "Implementation" | "Output-only"
    default_routing_package_id: str
    graph_builder: Callable[[], dict[str, Any]]
    policy_builder: Callable[[], dict[str, Any]]
    # Internal — name of the stock pipeline yaml fixture this recipe
    # mirrors (without ``.yaml``). Used by drift tests, not at runtime.
    _pipeline_fixture: str = ""


@dataclass(frozen=True)
class RoutingPackageSpec:
    """A named routing package.

    ``routes`` is a mapping of ``roles.*`` keys (and any named-route entries
    such as ``smart-advisor``) → ``{backend, model, effort}`` route dicts.
    """

    package_id: str
    display_name: str
    routes: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class GraphStackSpec:
    """A reusable graph stack template.

    ``stage_templates`` is the ordered list of stage mappings that make up
    the stack. ``default_dependencies`` is a mapping ``stage_id -> tuple``
    of default upstream dependencies (the union of ``depends_on`` arrays
    from each stage in the matching pipeline yaml).
    """

    stack_id: str
    display_name: str
    stage_templates: tuple[Mapping[str, Any], ...]
    default_dependencies: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class NewPresetBuildResult:
    """Builder output."""

    preset_mapping: Mapping[str, Any] = field(default_factory=dict)
    pipeline_mapping: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_PROVIDER_REVIEW_BLOCK: dict[str, Any] = {
    "type": "swarm-review",
    "command": "review",
    "selection": "auto",
    "output": "findings",
    "memory": False,
    "timeout_seconds": 1800,
    "max_parallel": 4,
}


def _provider_stage_default(stage_id: str, depends_on: list[str]) -> dict[str, Any]:
    """Return a provider-review stage mapping with the default block."""
    stage: dict[str, Any] = {"id": stage_id}
    if depends_on:
        stage["depends_on"] = list(depends_on)
    stage["provider"] = copy.deepcopy(_PROVIDER_REVIEW_BLOCK)
    stage["failure_tolerance"] = {"mode": "best-effort"}
    return stage


# Routing-table fragments shared across recipes.
_BALANCED_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-docs": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-spec-review": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-clarify": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-writer.simple": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
}

_CLAUDE_ONLY_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-research": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "high"},
    "roles.agent-analysis": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
    "roles.agent-debug": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
    "roles.agent-clarify": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "medium"},
    "roles.agent-writer.simple": {"backend": "claude", "model": "claude-haiku-4-5", "effort": "medium"},
    "roles.agent-writer.moderate": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "high"},
    "roles.agent-writer.hard": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-spec-review": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "medium"},
    "roles.agent-review": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-docs": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "medium"},
    "roles.agent-codex-review": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
}

_CODEX_ONLY_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-research": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
    "roles.agent-analysis": {"backend": "codex", "model": "gpt-5.4", "effort": "xhigh"},
    "roles.agent-debug": {"backend": "codex", "model": "gpt-5.4", "effort": "xhigh"},
    "roles.agent-clarify": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-writer.simple": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-writer.moderate": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
    "roles.agent-writer.hard": {"backend": "codex", "model": "gpt-5.4", "effort": "xhigh"},
    "roles.agent-spec-review": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-review": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
    "roles.agent-docs": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-codex-review": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
    "roles.agent-analysis-judge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-writer-judge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-code-synthesizer": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
}

_LIGHTWEIGHT_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-clarify": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-writer.simple": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
}

_HYBRID_REVIEW_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-codex-review": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
}

_ULTRA_PLAN_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-analysis.hard": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
    "roles.agent-analysis-judge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-writer.hard": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
}

_REPAIR_LOOP_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-docs": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-spec-review": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-clarify": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-writer.simple": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-clean-review": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
}

_SMART_FRIEND_ROUTES: dict[str, dict[str, Any]] = {
    "smart-advisor": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-docs": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-spec-review": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-clarify": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
    "roles.agent-writer.simple": {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
}

_COMPETITIVE_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-analysis": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
    "roles.agent-writer-judge": {"backend": "codex", "model": "gpt-5.4", "effort": "high"},
}

_RESEARCH_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-research": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "high"},
    "roles.agent-research-merge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
}

_BRAINSTORM_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-brainstorm": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "high"},
    "roles.agent-brainstorm-merge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
}

_DESIGN_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-research": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "high"},
    "roles.agent-analysis": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
    "roles.agent-analysis-judge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
    "roles.agent-clarify": {"backend": "claude", "model": "claude-sonnet-4-6", "effort": "medium"},
}

_REVIEW_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-review": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
}

_REVIEW_STRICT_ROUTES: dict[str, dict[str, Any]] = {
    "roles.agent-review": {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
}


# Common policy fragments
_DEFAULT_DECOMPOSE: dict[str, Any] = {"mode": "off"}
_DEFAULT_MEM_PRIME: dict[str, Any] = {
    "mode": "off",
    "max_tokens": 500,
    "recency_days": 90,
    "min_relevance": 0.6,
    "adapter": "dispatch_file",
}
_DEFAULT_REVIEW_PROVIDERS: dict[str, Any] = {
    "selection": "auto",
    "min_success": 1,
    "max_parallel": 4,
}


def _budget(
    *,
    agents: int,
    cost: float,
    seconds: int,
    writer_tool_calls: int | None = None,
    writer_output_bytes: int | None = None,
    handoffs: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "max_agents_per_run": agents,
        "max_estimated_cost_usd": cost,
        "max_wall_clock_seconds": seconds,
    }
    if writer_tool_calls is not None:
        out["max_writer_tool_calls"] = writer_tool_calls
    if writer_output_bytes is not None:
        out["max_writer_output_bytes"] = writer_output_bytes
    if handoffs is not None:
        out["max_handoffs"] = handoffs
    return out


# ---------------------------------------------------------------------------
# Graph builders — each returns a freshly-allocated pipeline_inline mapping
# ---------------------------------------------------------------------------


def _graph_default() -> dict[str, Any]:
    """Mirrors ``pipelines/default.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "default",
        "description": "Default research-analysis-clarify-writer-review-docs swarm pipeline.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {"id": "writer", "depends_on": ["analysis", "clarify"], "agents": [{"role": "agent-writer"}]},
            {"id": "spec-review", "depends_on": ["writer"], "agents": [{"role": "agent-spec-review"}]},
            _provider_stage_default("provider-review", ["writer"]),
            {"id": "review", "depends_on": ["spec-review", "provider-review"], "agents": [{"role": "agent-review"}]},
            {"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        ],
    }


def _graph_lightweight() -> dict[str, Any]:
    """Mirrors ``pipelines/lightweight.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "lightweight",
        "description": "Small-change pipeline without spec-review and docs stages.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {"id": "writer", "depends_on": ["analysis", "clarify"], "agents": [{"role": "agent-writer"}]},
            _provider_stage_default("provider-review", ["writer"]),
            {"id": "review", "depends_on": ["writer", "provider-review"], "agents": [{"role": "agent-review"}]},
        ],
    }


def _graph_hybrid_review() -> dict[str, Any]:
    """Mirrors ``pipelines/hybrid-review.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "hybrid-review",
        "description": "Default pipeline with provider evidence and fail-open Codex blocking-issues review before final review.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {"id": "writer", "depends_on": ["analysis", "clarify"], "agents": [{"role": "agent-writer"}]},
            {"id": "spec-review", "depends_on": ["writer"], "agents": [{"role": "agent-spec-review"}]},
            _provider_stage_default("provider-review", ["writer"]),
            {
                "id": "codex-review",
                "depends_on": ["spec-review"],
                "agents": [
                    {"role": "agent-codex-review", "backend": "codex", "model": "gpt-5.4", "effort": "high"}
                ],
                "failure_tolerance": {"mode": "best-effort"},
            },
            {
                "id": "review",
                "depends_on": ["spec-review", "provider-review", "codex-review"],
                "agents": [{"role": "agent-review"}],
            },
            {"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        ],
    }


def _graph_ultra_plan() -> dict[str, Any]:
    """Mirrors ``pipelines/ultra-plan.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "ultra-plan",
        "description": "Three prompt-variant planning explorers merged before writer.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {
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
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {"id": "writer", "depends_on": ["exploration", "clarify"], "agents": [{"role": "agent-writer"}]},
            {"id": "spec-review", "depends_on": ["writer"], "agents": [{"role": "agent-spec-review"}]},
            _provider_stage_default("provider-review", ["writer"]),
            {"id": "review", "depends_on": ["spec-review", "provider-review"], "agents": [{"role": "agent-review"}]},
            {"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        ],
    }


def _graph_repair_loop() -> dict[str, Any]:
    """Mirrors ``pipelines/repair-loop.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "repair-loop",
        "description": "Bounded evaluator-optimizer implementation flow with one clean-context review and revision cycle.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {"id": "writer", "depends_on": ["analysis", "clarify"], "agents": [{"role": "agent-writer"}]},
            {"id": "clean-review", "depends_on": ["writer"], "agents": [{"role": "agent-clean-review"}]},
            {
                "id": "revise-writer",
                "depends_on": ["writer", "clean-review"],
                "agents": [{"role": "agent-writer"}],
                "failure_tolerance": {"mode": "best-effort"},
            },
            {"id": "spec-review", "depends_on": ["revise-writer"], "agents": [{"role": "agent-spec-review"}]},
            _provider_stage_default("provider-review", ["revise-writer"]),
            {"id": "review", "depends_on": ["spec-review", "provider-review"], "agents": [{"role": "agent-review"}]},
            {"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        ],
    }


def _graph_smart_friend() -> dict[str, Any]:
    """Mirrors ``pipelines/smart-friend.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "smart-friend",
        "description": "Experimental implementation profile with a read-only advisor stage before the single writer.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {
                "id": "advisor",
                "depends_on": ["analysis", "clarify"],
                "agents": [{"role": "agent-implementation-advisor", "route": "smart-advisor"}],
            },
            {
                "id": "writer",
                "depends_on": ["analysis", "clarify", "advisor"],
                "agents": [{"role": "agent-writer"}],
            },
            {"id": "spec-review", "depends_on": ["writer"], "agents": [{"role": "agent-spec-review"}]},
            _provider_stage_default("provider-review", ["writer"]),
            {"id": "review", "depends_on": ["spec-review", "provider-review"], "agents": [{"role": "agent-review"}]},
            {"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        ],
    }


def _graph_compete() -> dict[str, Any]:
    """Mirrors ``pipelines/compete.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "compete",
        "description": "Pattern 5 competitive writer fan-out with a judge merge.",
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {"id": "analysis", "depends_on": ["research"], "agents": [{"role": "agent-analysis"}]},
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {
                "id": "writers",
                "depends_on": ["analysis", "clarify"],
                "fan_out": {
                    "role": "agent-writer",
                    "count": 2,
                    "variant": "models",
                    "routes": [
                        {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
                        {"backend": "codex", "model": "gpt-5.4", "effort": "xhigh"},
                    ],
                },
                "merge": {"strategy": "synthesize", "agent": "agent-writer-judge"},
                "failure_tolerance": {"mode": "strict"},
            },
            {"id": "spec-review", "depends_on": ["writers"], "agents": [{"role": "agent-spec-review"}]},
            {"id": "review", "depends_on": ["spec-review"], "agents": [{"role": "agent-review"}]},
            {"id": "docs", "depends_on": ["spec-review"], "agents": [{"role": "agent-docs"}]},
        ],
    }


def _graph_research() -> dict[str, Any]:
    """Mirrors ``pipelines/research.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "research",
        "description": "Research fan-out and synthesis memo pipeline with no implementation stages.",
        "parallelism": 3,
        "stages": [
            {
                "id": "research",
                "fan_out": {
                    "role": "agent-research",
                    "count": 3,
                    "variant": "prompt_variants",
                    "variants": ["codebase-map", "prior-art-search", "risk-discovery"],
                },
                "merge": {"strategy": "synthesize", "agent": "agent-research-merge"},
                "failure_tolerance": {"mode": "quorum", "min_success": 2},
            }
        ],
    }


def _graph_brainstorm() -> dict[str, Any]:
    """Mirrors ``pipelines/brainstorm.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "brainstorm",
        "description": "Multi-agent ideation fan-out and synthesis note with no implementation stages.",
        "parallelism": 3,
        "stages": [
            {
                "id": "brainstorm",
                "fan_out": {
                    "role": "agent-brainstorm",
                    "count": 3,
                    "variant": "prompt_variants",
                    "variants": [
                        "expand-options",
                        "constraints-and-failure-modes",
                        "analogies-and-transfers",
                    ],
                },
                "merge": {"strategy": "synthesize", "agent": "agent-brainstorm-merge"},
                "failure_tolerance": {"mode": "quorum", "min_success": 2},
            }
        ],
    }


def _graph_design() -> dict[str, Any]:
    """Mirrors ``pipelines/design.yaml``.

    NOTE: ``exploration`` count is 4 per the actual yaml fixture (variants
    explorer-a, explorer-b, explorer-c, security-threat-model) — the plan
    prose's count=3 is a documentation error; fixture is ground truth.
    """
    return {
        "pipeline_version": 1,
        "name": "design",
        "description": "Research, clarification, and analysis fan-out that closes with an execution-ready design note.",
        "parallelism": 3,
        "stages": [
            {"id": "research", "agents": [{"role": "agent-research"}]},
            {
                "id": "exploration",
                "depends_on": ["research"],
                "fan_out": {
                    "role": "agent-analysis",
                    "count": 4,
                    "variant": "prompt_variants",
                    "variants": [
                        "explorer-a",
                        "explorer-b",
                        "explorer-c",
                        "security-threat-model",
                    ],
                },
                "merge": {"strategy": "synthesize", "agent": "agent-analysis-judge"},
                "failure_tolerance": {"mode": "quorum", "min_success": 3},
            },
            {"id": "clarify", "depends_on": ["research"], "agents": [{"role": "agent-clarify"}]},
            {
                "id": "recommendation",
                "depends_on": ["research", "exploration", "clarify"],
                "agents": [{"role": "agent-analysis"}],
            },
        ],
    }


def _graph_review() -> dict[str, Any]:
    """Mirrors ``pipelines/review.yaml``."""
    return {
        "pipeline_version": 1,
        "name": "review",
        "description": "Output-only review fan-out with rubric lenses and a synthesized findings summary.",
        "parallelism": 5,
        "stages": [
            _provider_stage_default("provider-review", []),
            {
                "id": "review",
                "depends_on": ["provider-review"],
                "fan_out": {
                    "role": "agent-review",
                    "count": 5,
                    "variant": "prompt_variants",
                    "variants": [
                        "correctness-rubric",
                        "api-contract",
                        "security-threat-model",
                        "performance-review",
                        "edge-case-review",
                    ],
                },
                "merge": {"strategy": "synthesize", "agent": "agent-review"},
                "failure_tolerance": {"mode": "quorum", "min_success": 3},
            },
        ],
    }


def _graph_review_strict() -> dict[str, Any]:
    """Mirrors ``pipelines/review-strict.yaml``."""
    stage_provider: dict[str, Any] = {
        "id": "provider-review",
        "provider": copy.deepcopy(_PROVIDER_REVIEW_BLOCK),
        "failure_tolerance": {"mode": "quorum", "min_success": 2},
    }
    return {
        "pipeline_version": 1,
        "name": "review-strict",
        "description": "Output-only review evidence profile with stricter provider expectations and five-lens synthesis.",
        "parallelism": 5,
        "stages": [
            stage_provider,
            {
                "id": "review",
                "depends_on": ["provider-review"],
                "fan_out": {
                    "role": "agent-review",
                    "count": 5,
                    "variant": "prompt_variants",
                    "variants": [
                        "correctness-rubric",
                        "api-contract",
                        "security-threat-model",
                        "performance-review",
                        "edge-case-review",
                    ],
                },
                "merge": {"strategy": "synthesize", "agent": "agent-review"},
                "failure_tolerance": {"mode": "quorum", "min_success": 3},
            },
        ],
    }


# ---------------------------------------------------------------------------
# Policy builders — each returns the policy keys the matching stock fixture
# carries (no review_providers for output-only recipes that omit it).
# ---------------------------------------------------------------------------


def _policy_balanced() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_BALANCED_ROUTES),
        "budget": _budget(agents=80, cost=20.0, seconds=14400, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_claude_only() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_CLAUDE_ONLY_ROUTES),
        "budget": _budget(agents=80, cost=30.0, seconds=14400, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_codex_only() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_CODEX_ONLY_ROUTES),
        "budget": _budget(agents=80, cost=20.0, seconds=14400, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_lightweight() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_LIGHTWEIGHT_ROUTES),
        "budget": _budget(agents=40, cost=10.0, seconds=7200, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_hybrid_review() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_HYBRID_REVIEW_ROUTES),
        "budget": _budget(agents=100, cost=25.0, seconds=14400, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_ultra_plan() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_ULTRA_PLAN_ROUTES),
        "budget": _budget(agents=120, cost=35.0, seconds=21600, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_repair_loop() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_REPAIR_LOOP_ROUTES),
        "budget": _budget(agents=100, cost=28.0, seconds=18000, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_smart_friend() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_SMART_FRIEND_ROUTES),
        "budget": _budget(agents=100, cost=25.0, seconds=18000, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_competitive() -> dict[str, Any]:
    # competitive.toml has no review_providers block — omit it.
    return {
        "routing": copy.deepcopy(_COMPETITIVE_ROUTES),
        "budget": _budget(agents=120, cost=40.0, seconds=21600, writer_tool_calls=60, writer_output_bytes=60000, handoffs=1),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_research_memo() -> dict[str, Any]:
    # research.toml has no review_providers block.
    return {
        "routing": copy.deepcopy(_RESEARCH_ROUTES),
        "budget": _budget(agents=20, cost=8.0, seconds=7200),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_brainstorm() -> dict[str, Any]:
    # brainstorm.toml has no review_providers block.
    return {
        "routing": copy.deepcopy(_BRAINSTORM_ROUTES),
        "budget": _budget(agents=20, cost=8.0, seconds=7200),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_design_plan() -> dict[str, Any]:
    # design.toml has no review_providers block.
    return {
        "routing": copy.deepcopy(_DESIGN_ROUTES),
        "budget": _budget(agents=60, cost=20.0, seconds=14400),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_review_evidence() -> dict[str, Any]:
    return {
        "review_providers": dict(_DEFAULT_REVIEW_PROVIDERS),
        "routing": copy.deepcopy(_REVIEW_ROUTES),
        "budget": _budget(agents=30, cost=12.0, seconds=7200),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


def _policy_strict_review_evidence() -> dict[str, Any]:
    return {
        "review_providers": {"selection": "auto", "min_success": 2, "max_parallel": 4},
        "routing": copy.deepcopy(_REVIEW_STRICT_ROUTES),
        "budget": _budget(agents=35, cost=16.0, seconds=9000),
        "decompose": dict(_DEFAULT_DECOMPOSE),
        "mem_prime": dict(_DEFAULT_MEM_PRIME),
    }


# ---------------------------------------------------------------------------
# Routing packages
# ---------------------------------------------------------------------------


_ROUTING_PACKAGES: tuple[RoutingPackageSpec, ...] = (
    RoutingPackageSpec("balanced", "Balanced", _BALANCED_ROUTES),
    RoutingPackageSpec("claude-only", "Claude-Only", _CLAUDE_ONLY_ROUTES),
    RoutingPackageSpec("codex-only", "Codex-Only", _CODEX_ONLY_ROUTES),
    RoutingPackageSpec("lightweight", "Lightweight", _LIGHTWEIGHT_ROUTES),
    RoutingPackageSpec("hybrid-review", "Hybrid Review", _HYBRID_REVIEW_ROUTES),
    RoutingPackageSpec("ultra-plan", "Ultra Plan", _ULTRA_PLAN_ROUTES),
    RoutingPackageSpec("repair-loop", "Repair Loop", _REPAIR_LOOP_ROUTES),
    RoutingPackageSpec("smart-friend", "Smart Friend", _SMART_FRIEND_ROUTES),
    RoutingPackageSpec("competitive", "Competitive", _COMPETITIVE_ROUTES),
    RoutingPackageSpec("research", "Research", _RESEARCH_ROUTES),
    RoutingPackageSpec("brainstorm", "Brainstorm", _BRAINSTORM_ROUTES),
    RoutingPackageSpec("design", "Design", _DESIGN_ROUTES),
    RoutingPackageSpec("review", "Review", _REVIEW_ROUTES),
    RoutingPackageSpec("review-strict", "Strict Review", _REVIEW_STRICT_ROUTES),
)


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


_RECIPES: tuple[PresetRecipeSpec, ...] = (
    PresetRecipeSpec(
        recipe_id="balanced-default",
        display_name="Balanced Default",
        intent="Implementation",
        default_routing_package_id="balanced",
        graph_builder=_graph_default,
        policy_builder=_policy_balanced,
        _pipeline_fixture="default",
    ),
    PresetRecipeSpec(
        recipe_id="claude-only-diagnostic",
        display_name="Claude-Only Diagnostic",
        intent="Implementation",
        default_routing_package_id="claude-only",
        graph_builder=_graph_default,
        policy_builder=_policy_claude_only,
        _pipeline_fixture="default",
    ),
    PresetRecipeSpec(
        recipe_id="codex-only-fallback",
        display_name="Codex-Only Fallback",
        intent="Implementation",
        default_routing_package_id="codex-only",
        graph_builder=_graph_default,
        policy_builder=_policy_codex_only,
        _pipeline_fixture="default",
    ),
    PresetRecipeSpec(
        recipe_id="lightweight",
        display_name="Lightweight",
        intent="Implementation",
        default_routing_package_id="lightweight",
        graph_builder=_graph_lightweight,
        policy_builder=_policy_lightweight,
        _pipeline_fixture="lightweight",
    ),
    PresetRecipeSpec(
        recipe_id="hybrid-review",
        display_name="Hybrid Review",
        intent="Implementation",
        default_routing_package_id="hybrid-review",
        graph_builder=_graph_hybrid_review,
        policy_builder=_policy_hybrid_review,
        _pipeline_fixture="hybrid-review",
    ),
    PresetRecipeSpec(
        recipe_id="ultra-plan",
        display_name="Ultra Plan",
        intent="Implementation",
        default_routing_package_id="ultra-plan",
        graph_builder=_graph_ultra_plan,
        policy_builder=_policy_ultra_plan,
        _pipeline_fixture="ultra-plan",
    ),
    PresetRecipeSpec(
        recipe_id="repair-loop",
        display_name="Repair Loop",
        intent="Implementation",
        default_routing_package_id="repair-loop",
        graph_builder=_graph_repair_loop,
        policy_builder=_policy_repair_loop,
        _pipeline_fixture="repair-loop",
    ),
    PresetRecipeSpec(
        recipe_id="smart-friend",
        display_name="Smart Friend",
        intent="Implementation",
        default_routing_package_id="smart-friend",
        graph_builder=_graph_smart_friend,
        policy_builder=_policy_smart_friend,
        _pipeline_fixture="smart-friend",
    ),
    PresetRecipeSpec(
        recipe_id="competitive-implementation",
        display_name="Competitive Implementation",
        intent="Implementation",
        default_routing_package_id="competitive",
        graph_builder=_graph_compete,
        policy_builder=_policy_competitive,
        _pipeline_fixture="compete",
    ),
    PresetRecipeSpec(
        recipe_id="research-memo",
        display_name="Research Memo",
        intent="Output-only",
        default_routing_package_id="research",
        graph_builder=_graph_research,
        policy_builder=_policy_research_memo,
        _pipeline_fixture="research",
    ),
    PresetRecipeSpec(
        recipe_id="brainstorm",
        display_name="Brainstorm",
        intent="Output-only",
        default_routing_package_id="brainstorm",
        graph_builder=_graph_brainstorm,
        policy_builder=_policy_brainstorm,
        _pipeline_fixture="brainstorm",
    ),
    PresetRecipeSpec(
        recipe_id="design-plan",
        display_name="Design Plan",
        intent="Output-only",
        default_routing_package_id="design",
        graph_builder=_graph_design,
        policy_builder=_policy_design_plan,
        _pipeline_fixture="design",
    ),
    PresetRecipeSpec(
        recipe_id="review-evidence",
        display_name="Review Evidence",
        intent="Output-only",
        default_routing_package_id="review",
        graph_builder=_graph_review,
        policy_builder=_policy_review_evidence,
        _pipeline_fixture="review",
    ),
    PresetRecipeSpec(
        recipe_id="strict-review-evidence",
        display_name="Strict Review Evidence",
        intent="Output-only",
        default_routing_package_id="review-strict",
        graph_builder=_graph_review_strict,
        policy_builder=_policy_strict_review_evidence,
        _pipeline_fixture="review-strict",
    ),
)


# ---------------------------------------------------------------------------
# Graph stacks
# ---------------------------------------------------------------------------


def _stack_default_implementation() -> GraphStackSpec:
    """Matches ``pipelines/default.yaml``."""
    template = _graph_default()
    stages = tuple(template["stages"])
    deps: dict[str, tuple[str, ...]] = {
        stage["id"]: tuple(stage.get("depends_on", []))
        for stage in stages
    }
    return GraphStackSpec(
        stack_id="default-implementation",
        display_name="Default Implementation",
        stage_templates=stages,
        default_dependencies=deps,
    )


def _stack_default_research() -> GraphStackSpec:
    """Matches ``pipelines/research.yaml``."""
    template = _graph_research()
    stages = tuple(template["stages"])
    deps = {stage["id"]: tuple(stage.get("depends_on", [])) for stage in stages}
    return GraphStackSpec(
        stack_id="default-research",
        display_name="Default Research",
        stage_templates=stages,
        default_dependencies=deps,
    )


def _stack_default_design() -> GraphStackSpec:
    """Matches ``pipelines/design.yaml``."""
    template = _graph_design()
    stages = tuple(template["stages"])
    deps = {stage["id"]: tuple(stage.get("depends_on", [])) for stage in stages}
    return GraphStackSpec(
        stack_id="default-design",
        display_name="Default Design",
        stage_templates=stages,
        default_dependencies=deps,
    )


def _stack_default_review() -> GraphStackSpec:
    """Matches ``pipelines/review.yaml``."""
    template = _graph_review()
    stages = tuple(template["stages"])
    deps = {stage["id"]: tuple(stage.get("depends_on", [])) for stage in stages}
    return GraphStackSpec(
        stack_id="default-review",
        display_name="Default Review",
        stage_templates=stages,
        default_dependencies=deps,
    )


_GRAPH_STACKS: tuple[GraphStackSpec, ...] = (
    _stack_default_implementation(),
    _stack_default_research(),
    _stack_default_design(),
    _stack_default_review(),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_preset_recipes() -> list[PresetRecipeSpec]:
    """Return all registered preset recipes (registration order)."""
    return list(_RECIPES)


def get_preset_recipe(recipe_id: str) -> PresetRecipeSpec:
    for recipe in _RECIPES:
        if recipe.recipe_id == recipe_id:
            return recipe
    raise KeyError(f"unknown preset recipe: {recipe_id}")


def list_routing_packages() -> list[RoutingPackageSpec]:
    return list(_ROUTING_PACKAGES)


def get_routing_package(package_id: str) -> RoutingPackageSpec:
    for package in _ROUTING_PACKAGES:
        if package.package_id == package_id:
            return package
    raise KeyError(f"unknown routing package: {package_id}")


def list_graph_stacks() -> list[GraphStackSpec]:
    return list(_GRAPH_STACKS)


def get_graph_stack(stack_id: str) -> GraphStackSpec:
    for stack in _GRAPH_STACKS:
        if stack.stack_id == stack_id:
            return stack
    raise KeyError(f"unknown graph stack: {stack_id}")


def _validate_built(
    name: str,
    preset_mapping: Mapping[str, Any],
    pipeline_mapping: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Run validation gates and return (errors, warnings)."""
    result, _ = validate_preset_mapping(preset_mapping, name, include_budget=False)
    errors = list(result.errors)
    warnings = list(result.warnings)
    activation_error = pipeline_activation_error(name, pipeline_mapping)
    if activation_error:
        warnings.append(activation_error)
    return tuple(errors), tuple(warnings)


def build_recipe_preset(
    recipe_id: str,
    name: str,
    description: str | None = None,
    routing_package_id: str | None = None,
) -> NewPresetBuildResult:
    """Build a preset mapping from a recipe.

    The produced preset has ``origin = "user"`` and the inline pipeline
    mapping under ``pipeline_inline``. The selected routing package's
    routes replace ``routing``.
    """
    recipe = get_preset_recipe(recipe_id)
    package_id = routing_package_id or recipe.default_routing_package_id
    package = get_routing_package(package_id)

    desc = description if description is not None else recipe.display_name

    pipeline_mapping = recipe.graph_builder()
    pipeline_mapping["name"] = name
    pipeline_mapping["description"] = desc

    policy = recipe.policy_builder()
    # Override routing with the selected routing package (deep-copy to
    # ensure the spec's static routes are not mutated by callers).
    policy["routing"] = copy.deepcopy(dict(package.routes))

    preset_mapping: dict[str, Any] = {
        "name": name,
        "description": desc,
        "origin": "user",
        "pipeline_inline": pipeline_mapping,
    }
    for key, value in policy.items():
        preset_mapping[key] = value

    errors, warnings = _validate_built(name, preset_mapping, pipeline_mapping)
    return NewPresetBuildResult(
        preset_mapping=preset_mapping,
        pipeline_mapping=pipeline_mapping,
        errors=errors,
        warnings=warnings,
    )


def build_blank_preset_draft(name: str, description: str) -> NewPresetBuildResult:
    """Build a preset mapping with an empty pipeline ``stages`` list.

    The resulting preset will fail ``schema_lint_pipeline`` (which requires
    a non-empty stages array). That error is propagated, not suppressed —
    callers are expected to surface it in the UI and disable Save until
    stages are added.
    """
    pipeline_mapping: dict[str, Any] = {
        "pipeline_version": 1,
        "name": name,
        "description": description,
        "stages": [],
    }
    preset_mapping: dict[str, Any] = {
        "name": name,
        "description": description,
        "origin": "user",
        "pipeline_inline": pipeline_mapping,
    }
    errors, warnings = _validate_built(name, preset_mapping, pipeline_mapping)
    return NewPresetBuildResult(
        preset_mapping=preset_mapping,
        pipeline_mapping=pipeline_mapping,
        errors=errors,
        warnings=warnings,
    )


def _stages_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Structural equality for two stage mappings."""
    return dict(left) == dict(right)


def apply_graph_stack(
    pipeline: Mapping[str, Any],
    stack_id: str,
    mode: str,
) -> NewPresetBuildResult:
    """Apply a graph stack to a pipeline mapping.

    Modes:
    - ``empty``: applies unconditionally; replaces ``stages``.
    - ``append-missing``: appends only stages whose ids are not already
      present. Refuses (via errors tuple) if a stage id collides but the
      existing stage differs from the stack template, or if any
      dependency points to a missing stage after append resolution.
    - ``replace``: replaces ``stages`` and any graph-level metadata the
      stack supplies (e.g., ``parallelism`` if present in stage_templates
      — note: stage_templates carry stages only; replace preserves
      pipeline-level keys other than ``stages``).

    Returns a ``NewPresetBuildResult`` whose ``pipeline_mapping`` carries
    the new pipeline. ``preset_mapping`` is empty — callers integrate
    the result back into a draft.
    """
    if mode not in {"empty", "append-missing", "replace"}:
        return NewPresetBuildResult(
            preset_mapping={},
            pipeline_mapping=dict(pipeline),
            errors=(f"unknown apply_graph_stack mode: {mode}",),
            warnings=(),
        )

    stack = get_graph_stack(stack_id)
    new_pipeline: dict[str, Any] = copy.deepcopy(dict(pipeline))
    existing_stages = list(new_pipeline.get("stages", []))
    template_stages = [copy.deepcopy(dict(stage)) for stage in stack.stage_templates]

    errors: list[str] = []

    if mode == "empty":
        if existing_stages:
            errors.append(
                "apply_graph_stack mode='empty' requires an empty stages list; "
                f"found {len(existing_stages)} existing stage(s)"
            )
            return NewPresetBuildResult(
                preset_mapping={},
                pipeline_mapping=new_pipeline,
                errors=tuple(errors),
                warnings=(),
            )
        new_pipeline["stages"] = template_stages
        return NewPresetBuildResult(
            preset_mapping={},
            pipeline_mapping=new_pipeline,
            errors=(),
            warnings=(),
        )

    if mode == "append-missing":
        existing_by_id: dict[str, Mapping[str, Any]] = {
            str(stage.get("id")): stage for stage in existing_stages if isinstance(stage, Mapping)
        }
        appended: list[Mapping[str, Any]] = []
        for template in template_stages:
            tid = str(template.get("id"))
            if tid in existing_by_id:
                if not _stages_equal(existing_by_id[tid], template):
                    errors.append(
                        f"append-missing: stage id '{tid}' already exists and differs from stack template"
                    )
                continue
            appended.append(template)
        if errors:
            return NewPresetBuildResult(
                preset_mapping={},
                pipeline_mapping=new_pipeline,
                errors=tuple(errors),
                warnings=(),
            )
        merged_stages = list(existing_stages) + appended
        # Verify all dependencies resolve.
        merged_ids = {
            str(stage.get("id")) for stage in merged_stages if isinstance(stage, Mapping)
        }
        for stage in merged_stages:
            if not isinstance(stage, Mapping):
                continue
            for dep in stage.get("depends_on", []) or []:
                if str(dep) not in merged_ids:
                    errors.append(
                        f"append-missing: stage '{stage.get('id')}' depends on missing stage '{dep}'"
                    )
        if errors:
            return NewPresetBuildResult(
                preset_mapping={},
                pipeline_mapping=new_pipeline,
                errors=tuple(errors),
                warnings=(),
            )
        new_pipeline["stages"] = merged_stages
        return NewPresetBuildResult(
            preset_mapping={},
            pipeline_mapping=new_pipeline,
            errors=(),
            warnings=(),
        )

    # mode == "replace"
    new_pipeline["stages"] = template_stages
    return NewPresetBuildResult(
        preset_mapping={},
        pipeline_mapping=new_pipeline,
        errors=(),
        warnings=(),
    )


__all__ = [
    "PresetRecipeSpec",
    "RoutingPackageSpec",
    "GraphStackSpec",
    "NewPresetBuildResult",
    "list_preset_recipes",
    "get_preset_recipe",
    "list_routing_packages",
    "get_routing_package",
    "list_graph_stacks",
    "get_graph_stack",
    "build_recipe_preset",
    "build_blank_preset_draft",
    "apply_graph_stack",
]
