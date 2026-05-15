from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_MODEL_IDS = {
    "claude_sonnet": "claude-sonnet-4-6",
    "claude_opus": "claude-opus-4-7",
    "claude_haiku": "claude-haiku-4-5-20251001",
    "codex": "gpt-5.5",
    "codex_gpt5": "gpt-5",
}

SCOPE_INSTRUCTIONS = {
    "codebase": "Search the current working directory and cite as `path/to/file.ext:line`. Do not invoke web search.",
    "web": "Search the web and cite as full URLs. Do not assume the user's codebase is available.",
    "mixed": "Use both the codebase and web search. Cite as `path:line` for code, full URLs for web.",
}

SCOPE_POLICY_DEFAULT = "best_effort"
SCOPE_POLICY_VALUES = ("advisory", "best_effort", "required")


class ScopeEnforcementError(ValueError):
    """Raised when required scope controls cannot be applied."""


def build_participant_argv(
    participant: dict[str, Any],
    *,
    cwd: str | Path | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    backend = participant["backend"]
    model = participant["model"]
    effort = participant.get("effort", "high")
    extras = list(extra_args or [])
    if backend == "claude":
        return ["claude", "-p", "--model", model, "--effort", effort, *extras]
    if backend == "codex":
        argv = ["codex", "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "--skip-git-repo-check"]
        argv.extend(extras)
        if cwd is not None:
            argv.extend(["-C", str(cwd)])
        return argv
    raise ValueError(f"unsupported backend: {backend}")


def version_argv(backend: str) -> list[str]:
    if backend == "claude":
        return ["claude", "--version"]
    if backend == "codex":
        return ["codex", "--version"]
    if backend == "git":
        return ["git", "--version"]
    raise ValueError(f"unsupported tool: {backend}")


@lru_cache(maxsize=None)
def detect_scope_capabilities(backend: str) -> dict[str, Any]:
    """Best-effort local capability probe from installed CLI help text."""
    argv = scope_help_argv(backend)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "backend": backend,
            "available": False,
            "supports": {},
            "probe_error": f"{exc.__class__.__name__}: {exc}",
        }
    return scope_capabilities_from_help(backend, f"{result.stdout}\n{result.stderr}")


def scope_help_argv(backend: str) -> list[str]:
    if backend == "claude":
        return ["claude", "-p", "--help"]
    if backend == "codex":
        return ["codex", "exec", "--help"]
    raise ValueError(f"unsupported backend: {backend}")


def scope_capabilities_from_help(backend: str, help_text: str) -> dict[str, Any]:
    options = help_option_tokens(help_text)
    supports: dict[str, bool]
    if backend == "claude":
        supports = {
            "allowed_tools": has_help_option(options, "--allowedTools", "--allowed-tools"),
            "disallowed_tools": has_help_option(options, "--disallowedTools", "--disallowed-tools"),
            "tools": has_help_option(options, "--tools"),
            "permission_mode": has_help_option(options, "--permission-mode"),
        }
    elif backend == "codex":
        supports = {
            "sandbox": has_help_option(options, "--sandbox"),
            "disable_feature": has_help_option(options, "--disable"),
            "profile": has_help_option(options, "--profile"),
            "config": has_help_option(options, "--config"),
        }
    else:
        raise ValueError(f"unsupported backend: {backend}")
    return {"backend": backend, "available": True, "supports": supports}


def help_option_tokens(help_text: str) -> set[str]:
    return set(re.findall(r"--[A-Za-z0-9][A-Za-z0-9-]*", help_text))


def has_help_option(options: set[str], *names: str) -> bool:
    return any(name in options for name in names)


def build_scope_execution(
    participant: dict[str, Any],
    scope_policy: dict[str, Any],
    *,
    workspace_cwd: Path,
    run_dir: Path,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_scope = participant.get("scope", "mixed")
    policy = scope_policy.get("enforcement", SCOPE_POLICY_DEFAULT)
    backend = participant["backend"]
    execution_cwd = workspace_cwd
    mechanisms: list[str] = []
    fallback_reasons: list[str] = []
    extra_args: list[str] = []
    cleanup_paths: list[Path] = []

    if policy == "advisory":
        return _scope_execution_result(
            participant,
            execution_cwd=execution_cwd,
            extra_args=extra_args,
            cleanup_paths=cleanup_paths,
            policy=policy,
            requested_scope=requested_scope,
            effective_scope="advisory",
            enforcement_level="advisory",
            mechanisms=mechanisms,
            fallback_reasons=[],
        )

    caps = capabilities or detect_scope_capabilities(backend)
    supports = caps.get("supports") if isinstance(caps.get("supports"), dict) else {}
    needs_isolated_cwd = requested_scope == "web"
    if requested_scope == "web":
        mechanisms.append("isolated_cwd")

    if requested_scope == "mixed":
        mechanisms.append("mixed_scope_no_restriction")
    elif backend == "claude":
        if requested_scope == "codebase":
            if supports.get("disallowed_tools"):
                extra_args.extend(["--disallowedTools", "WebFetch", "WebSearch"])
                mechanisms.append("claude:disallowedTools=WebFetch,WebSearch")
            else:
                fallback_reasons.append("claude CLI did not advertise --disallowedTools")
        elif requested_scope == "web":
            if supports.get("allowed_tools"):
                extra_args.extend(["--allowedTools", "WebFetch", "WebSearch"])
                mechanisms.append("claude:allowedTools=WebFetch,WebSearch")
            else:
                fallback_reasons.append("claude CLI did not advertise --allowedTools")
    elif backend == "codex":
        if requested_scope in {"codebase", "web"}:
            if supports.get("sandbox"):
                extra_args.extend(["--sandbox", "read-only"])
                mechanisms.append("codex:sandbox=read-only")
            else:
                fallback_reasons.append("codex CLI did not advertise --sandbox")
        if requested_scope == "codebase":
            if supports.get("disable_feature"):
                extra_args.extend(["--disable", "web_search"])
                mechanisms.append("codex:disable=web_search")
            else:
                fallback_reasons.append("codex CLI did not advertise --disable")

    enforcement_level = "enforced" if requested_scope == "mixed" else "partial"
    if not mechanisms:
        enforcement_level = "advisory"
    if fallback_reasons and policy == "required":
        raise ScopeEnforcementError("; ".join(fallback_reasons))

    if needs_isolated_cwd:
        execution_cwd = make_scope_workspace(run_dir.name, participant["id"])
        cleanup_paths.append(execution_cwd)

    return _scope_execution_result(
        participant,
        execution_cwd=execution_cwd,
        extra_args=extra_args,
        cleanup_paths=cleanup_paths,
        policy=policy,
        requested_scope=requested_scope,
        effective_scope=requested_scope if enforcement_level != "advisory" else "advisory",
        enforcement_level=enforcement_level,
        mechanisms=mechanisms,
        fallback_reasons=fallback_reasons,
    )


def _scope_execution_result(
    participant: dict[str, Any],
    *,
    execution_cwd: Path,
    extra_args: list[str],
    cleanup_paths: list[Path],
    policy: str,
    requested_scope: str,
    effective_scope: str,
    enforcement_level: str,
    mechanisms: list[str],
    fallback_reasons: list[str],
) -> dict[str, Any]:
    metadata = {
        "requested_scope": requested_scope,
        "policy": policy,
        "effective_scope": effective_scope,
        "enforcement_level": enforcement_level,
        "mechanisms": mechanisms,
        "fallback_reason": "; ".join(fallback_reasons) if fallback_reasons else None,
        "cwd": str(execution_cwd),
        "temporary_cwd": bool(cleanup_paths),
    }
    return {
        "argv": build_participant_argv(participant, cwd=execution_cwd, extra_args=extra_args),
        "cwd": execution_cwd,
        "cleanup_paths": cleanup_paths,
        "metadata": metadata,
    }


def make_scope_workspace(run_id: str, provider_id: str) -> Path:
    prefix = f"bakeoff-{safe_temp_prefix(run_id)}-{safe_temp_prefix(provider_id)}-"
    path = Path(tempfile.mkdtemp(prefix=prefix))
    os.chmod(path, 0o700)
    return path


def safe_temp_prefix(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value)[:80] or "scope"


def build_worker_prompt(work_order: dict[str, Any], provider: dict[str, Any]) -> str:
    mode = work_order["type"]
    if mode == "gather":
        template = GATHER_WORKER_PROMPT
    elif mode == "compare":
        template = COMPARE_WORKER_PROMPT
    elif mode == "analyze":
        template = ANALYZE_WORKER_PROMPT
    else:
        raise ValueError(f"unsupported mode: {mode}")
    return (
        template.replace("{GOAL}", work_order["goal"])
        .replace("{BACKGROUND}", work_order["background"])
        .replace("{SCOPE_INSTRUCTIONS}", SCOPE_INSTRUCTIONS[provider["scope"]])
        .replace("{WORKER_RESULT_SCHEMA}", WORKER_RESULT_SCHEMA)
    )


def build_judge_prompt(
    work_order: dict[str, Any],
    worker_a: dict[str, Any],
    worker_b: dict[str, Any],
    *,
    mode: str | None = None,
) -> str:
    actual_mode = mode or work_order["type"]
    payload_a = json.dumps(worker_a, indent=2, sort_keys=True)
    payload_b = json.dumps(worker_b, indent=2, sort_keys=True)
    if actual_mode == "gather":
        return GATHER_JUDGE_PROMPT.replace("{FINAL_JSON_A}", payload_a).replace("{FINAL_JSON_B}", payload_b)
    if actual_mode == "compare":
        return COMPARE_JUDGE_PROMPT.replace("{FINAL_JSON_A}", payload_a).replace("{FINAL_JSON_B}", payload_b)
    if actual_mode == "analyze":
        return ANALYZE_JUDGE_PROMPT.replace("{FINAL_JSON_A}", payload_a).replace("{FINAL_JSON_B}", payload_b)
    raise ValueError(f"unsupported mode: {actual_mode}")


def build_triage_prompt(triage_payload: dict[str, Any]) -> str:
    payload = json.dumps(triage_payload, indent=2, sort_keys=True)
    return TRIAGE_PROMPT.replace("{TRIAGE_PAYLOAD}", payload).replace("{TRIAGE_RESULT_SCHEMA}", TRIAGE_RESULT_SCHEMA)


def anonymized_worker_output(result: dict[str, Any]) -> dict[str, Any]:
    """Return only the parsed worker artifact; no provider id or transcript data."""
    final_json = result.get("final_json")
    if not isinstance(final_json, dict):
        return {}
    return final_json


WORKER_RESULT_SCHEMA = """\
All worker <final_json> payloads MUST include this top-level shape:

{
  "status": "complete",
  "claims": [
    {
      "id": "R-001",
      "claim": "One factual assertion, defended position claim, or analysis step.",
      "evidence": ["path/to/file.ext:line or https://example.com/source or doc heading"],
      "confidence": "high"
    }
  ],
  "conflicts": [],
  "unknowns": [],
  "recommended_next_checks": []
}

Allowed status values: "complete", "complete_with_concerns", "needs_context", "blocked".
Allowed confidence values: "high", "medium", "low".
Confidence reflects evidence strength, not agreement between providers: use "high" only when cited evidence directly proves the claim, "medium" when the citation supports the claim but requires interpretation or broader context, and "low" when evidence is indirect, incomplete, stale, or only partially supportive.
Every claims[] item MUST include these required fields with these exact names: "id", "claim", "evidence", "confidence".
Do not rename fields. Use "claim", not "finding", "summary", or "description". Use "evidence", not "citation", "citations", "source", or "sources".
Put unverified material in unknowns[] as strings instead of adding uncited claims.
"""


TRIAGE_RESULT_SCHEMA = """\
{
  "schema_version": 1,
  "status": "complete",
  "summary": "Short assessment of report quality and actionability.",
  "items": [
    {
      "id": "T-001",
      "source_finding_id": "F-001",
      "source_finding": "The report finding being triaged.",
      "classification": "real_issue",
      "severity": "medium",
      "confidence": "high",
      "supporting_evidence": ["src/bakeoff/cli.py:631"],
      "counterevidence": ["tests/test_modes_end_to_end.py:19"],
      "citation_check_ids": ["C-001", "C-014"],
      "recommended_action": "fix_now",
      "rationale": "Why this is or is not actionable."
    }
  ],
  "unknowns": ["Any checks triage could not perform."]
}

Allowed classification values: real_issue, false_positive, plan_doc_drift, product_decision, needs_repro, already_fixed, evidence_gap.
Allowed recommended_action values: fix_now, document, defer, ignore, reproduce.
Allowed severity values: high, medium, low, none.
Allowed confidence values: high, medium, low.
"""


TRIAGE_PROMPT = """You are a senior engineer doing evidence-grounded triage of a Bakeoff report.
You are NOT the original judge.
Your job is not to improve the report prose.
Your job is to classify only the provided actionable-looking source_findings.

<rules>
- Classify each entry in triage_payload.source_findings by source_finding_id.
- Do not create items for findings that are only present in report_md and absent from source_findings.
- If source_findings is empty, emit an empty items[] array and explain that no actionable-looking findings were selected.
- Check supporting citations when possible using the provided citation_checks data.
- Look for counterevidence in the provided artifacts and codebase.
- Verify that each source finding faithfully describes its supporting citations; citation_checks prove location existence, not semantic accuracy.
- Decide whether it should be fixed now, deferred, documented, ignored, or reproduced.
- Do not mark a finding real just because the report said it confidently.
- Do not mark a finding false just because it is inconvenient.
- If evidence is missing, use needs_repro or evidence_gap.
- Keep summary consistent with item classifications and rationales; do not assign blame or correctness in the summary unless the items say the same thing.
- Do not mutate the original decision or report.
</rules>

<triage_payload>
{TRIAGE_PAYLOAD}
</triage_payload>

<triage_result_schema>
{TRIAGE_RESULT_SCHEMA}
</triage_result_schema>

<output_format>
Reason privately if needed, then emit only one JSON object wrapped in <final_json>...</final_json>, matching the triage schema. No prose before or after the final_json block.
</output_format>
"""


GATHER_WORKER_PROMPT = """You are a research worker. Your job is to enumerate facts, references, and existing artifacts relevant to the question - NOT to synthesize, recommend, or pick a winner. A separate judge will deduplicate your output against a peer worker's output later.

<question>
{GOAL}
</question>

<context>
{BACKGROUND}
</context>

<scope>
{SCOPE_INSTRUCTIONS}
</scope>

<rules>
- Enumerate findings. Do NOT synthesize, rank, or recommend.
- Every claim MUST carry a citation: file:line, URL, or doc heading. If you cannot cite it, omit it from `claims` and add it to `unknowns`.
- Do not invent citations. If a source is not in <context> and not retrievable, do not claim it.
- Prefer breadth over depth. Surface 5-15 distinct findings rather than 2 exhaustive ones.
- If two findings contradict, list both - do not resolve the conflict.
- If you do not know, return `unknowns` rather than guessing.
- Confidence is one of: high, medium, low. Default to medium when uncertain.
</rules>

<worker_result_schema>
{WORKER_RESULT_SCHEMA}
</worker_result_schema>

<process>
1. In <scratchpad> tags, list candidate findings and their sources. Cross out any you cannot cite.
2. For each remaining finding, ask: "Is this a fact, or my opinion?" Drop opinions.
3. Emit the JSON object matching the worker result schema. No prose outside the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>, matching the worker result schema (status, claims[], conflicts[], unknowns[], recommended_next_checks[]). No content after </final_json>.
</output_format>
"""

COMPARE_WORKER_PROMPT = """You are answering a comparison question. Your job:
1. Reach a position on the question - pick one option, or "neither", or "either is acceptable".
2. Mount the strongest honest defense of the position you reach - not a balanced essay. A judge will later weigh your case against a peer worker who answered the same question independently.

<question>
{GOAL}
</question>

<context>
{BACKGROUND}
</context>

<scope>
{SCOPE_INSTRUCTIONS}
</scope>

<rules>
- First decide your position; then defend it. Do not hedge after you've decided.
- State your `position` as a single declarative sentence ("X is the right choice because...", "Neither X nor Y because...", "X and Y are equivalent for this use case").
- Honesty constraint: if a fact undercuts your position, acknowledge it in tradeoffs rather than hiding it. Hidden weaknesses cost you credibility with the judge.
- Cite evidence as file:line, URL, or doc heading. Do not invent citations.
- Distinguish CLAIM (what you assert) from EVIDENCE (why a third party should believe it) from TRADEOFF (what you give up).
- If you cannot defend a sub-claim, drop it rather than weakening it with "may" / "might" / "could potentially".
- Confidence is one of: high, medium, low.
</rules>

<worker_result_schema>
{WORKER_RESULT_SCHEMA}
Compare mode MUST also include this top-level field:
{
  "position": "One declarative sentence naming the answer you defend."
}
</worker_result_schema>

<process>
1. In <scratchpad>, decide your position. List the 3-5 strongest claims for it and the 2-3 strongest counter-arguments you must address.
2. For each claim, locate concrete evidence. Drop claims you cannot ground.
3. Decide which tradeoffs to surface honestly (judges penalize hidden ones).
4. Emit the JSON object per the worker result schema. No prose outside the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>, matching the worker result schema, plus a top-level `position` field (the one-sentence thesis you defended). The `claims[]` array carries the position's claims; the `conflicts[]` array carries the position's acknowledged tradeoffs (claims against your own position you choose to surface). No content after </final_json>.
</output_format>
"""

ANALYZE_WORKER_PROMPT = """You are producing an analysis/explanation of the subject below. A judge will later select your analysis or a peer's as the "spine" and overlay the loser's annotations onto the winner. Optimize for: a clear spine of reasoning, with each step independently checkable.

<subject>
{GOAL}
</subject>

<context>
{BACKGROUND}
</context>

<scope>
{SCOPE_INSTRUCTIONS}
</scope>

<rules>
- Produce a linear chain of reasoning steps. Each step is a discrete, atomic claim that a peer could independently mark "agrees", "disagrees", or "adds nuance".
- Number your steps. Avoid forward references ("as discussed below"); a later merger may overlay annotations on each step independently.
- Cite evidence per step (file:line, URL, or doc heading). Do not invent citations.
- Mark each step with a confidence in {high, medium, low}. Low-confidence steps invite peer corrections.
- If a step depends on an assumption, surface the assumption explicitly as its own step.
- Do not summarize at the end. The judge handles synthesis.
</rules>

<worker_result_schema>
{WORKER_RESULT_SCHEMA}
For analyze mode, the claims[] array IS your spine. Each claim object is one numbered, atomic analysis step.
</worker_result_schema>

<process>
1. In <scratchpad>, sketch the spine: what is the minimum sequence of steps a reader needs to reach the conclusion?
2. For each step, write one atomic claim + its evidence. Split compound steps.
3. Self-check: can a reader disagree with any single step without invalidating the whole? If not, split further.
4. Emit JSON per the worker result schema. No prose outside the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>, matching the worker result schema. The `claims[]` array IS your spine - each entry is one atomic step, in order, with its own evidence and confidence. No content after </final_json>.
</output_format>
"""

GATHER_JUDGE_PROMPT = """You are a deduplication and conflict-flagging judge. You receive two coverage outputs (A and B) from research workers. Your job: produce a single unified union - merge duplicates, surface conflicts, preserve citations. Do NOT pick a winner.

You do not know which model produced A or B. Use the positional labels "A" and "B" only.

<worker_a_output>
{FINAL_JSON_A}
</worker_a_output>

<worker_b_output>
{FINAL_JSON_B}
</worker_b_output>

<rules>
- Merge claims that make the SAME assertion about the SAME entity, regardless of wording. Preserve all citations from both sources on the merged claim, and tag `sources` using the positional labels: ["A"], ["B"], or ["A","B"].
- If two claims make CONFLICTING assertions, do NOT pick a side. Emit a conflict entry listing both claims (`claim_a`, `claim_b`), both citations, and a one-line description of the disagreement.
- Preserve confidence. If two merged claims have different confidences, take the lower.
- Confidence reflects evidence strength, not corroboration. Do not raise confidence during judging. Use `sources` to show whether one or both workers found a claim.
- Do not introduce new claims. You may only union, dedupe, and flag.
- Leave near-duplicates separate when in doubt. Over-merging is the dominant failure mode of dedupe judges.
</rules>

<process>
1. In <scratchpad>, pair up claims that appear to be the same assertion. Note any near-duplicates you are unsure about - leave them separate if in doubt.
2. Identify direct conflicts.
3. Emit the unified JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>: merged_claims[] (with claim, evidence[], sources[] in {"A","B"}, confidence), conflicts[] (with claim_a, claim_b, evidence), unknowns_union[]. No content after </final_json>.
</output_format>
"""

COMPARE_JUDGE_PROMPT = """You are a pairwise judge. You will see two defended positions, A and B. Read each position's `position` field first.

If A and B defend the SAME position (semantically - same answer to the underlying question), emit `relation: "consensus"`, do NOT pick a winner, and instead identify (a) the strongest evidence each side brings and (b) any disagreements within the shared position.

If A and B defend DIFFERENT positions, emit `relation: "compare"` and pick a winner OR declare a tie. Be strict: prefer well-evidenced reasoning over verbose advocacy.

You do not know which model produced A or B. Use positional labels only.

<position_a>
{FINAL_JSON_A}
</position_a>

<position_b>
{FINAL_JSON_B}
</position_b>

<rubric>
Score each position on a 1-5 scale on each of:
1. Evidence quality - are claims grounded in verifiable citations?
2. Argument coherence - do claims actually support the thesis?
3. Tradeoff honesty - does the position acknowledge real costs?
4. Rebuttal strength - does it engage anticipated objections?

Length is NOT a virtue. A concise, well-evidenced position beats a verbose, weakly-evidenced one.
</rubric>

<rules>
- Determine `relation` first ("consensus" or "compare") based on the `position` fields.
- Explain reasoning BEFORE the verdict. Score each position on each rubric dimension before naming a winner.
- The harness will call you TWICE with positions swapped. Your verdict must be driven by the rubric, not by which position appears first. If the two positions are within rubric-noise of each other, declare TIE.
- A verdict of "tie" is valid and expected when both positions defend their cases roughly equally well, or when both have similar critical flaws.
- In the `consensus` case, populate `consensus_strongest[]` with the best-evidenced claim from each side and `consensus_disagreements[]` with any sub-claim disagreements. Set `winner` to `null`.
- Do not penalize a position for being shorter if it covers the rubric.
- Do not invent evidence that neither position cited.
</rules>

<process>
1. In <scratchpad>, compare the `position` fields to decide `relation`.
2. Score A on each rubric dimension (1-5). Then score B. Then compare margins.
3. Emit the JSON verdict.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>: relation in {"consensus","compare"}, scores_a {evidence, coherence, tradeoff_honesty, rebuttals} with integer values from 1 to 5, scores_b {...}, winner in {"A","B","tie",null}, rationale (2-4 sentences citing rubric dimensions), kept_from_nonwinner[] (claims worth preserving - from the loser in `compare`, or one from each side in `consensus`), consensus_strongest[] (populated only when relation="consensus"), consensus_disagreements[] (populated only when relation="consensus"). No content after </final_json>.
</output_format>
"""

ANALYZE_JUDGE_PROMPT = """You are a synthesis judge. You receive two analyses (A and B) of the same subject. Your job:
1. Pick one analysis as the SPINE (the better backbone of reasoning).
2. Walk through the spine step-by-step. For each spine step, find the closest matching step in the loser and emit an annotation: `agrees`, `disagrees` (with one-line reason), `adds` (with one-line addition), or `not_covered`.
3. Append loser steps that do not map to any spine step as `additions_from_loser[]`.

<analysis_a>
{FINAL_JSON_A}
</analysis_a>

<analysis_b>
{FINAL_JSON_B}
</analysis_b>

<rubric>
Score each analysis on a 1-5 scale on each of:
1. Step atomicity - can each step be independently checked?
2. Citation grounding - are steps evidenced?
3. Assumption transparency - are hidden premises surfaced?
4. Coherence - do the steps actually compose into the conclusion?

Length and verbosity do NOT favor a spine.
</rubric>

<rules>
- Explain reasoning BEFORE the verdict. Score both analyses on the rubric before picking the spine.
- The harness calls you twice with positions swapped. Your spine choice must be rubric-driven, not position-driven.
- For each spine step, the annotation must reflect the LOSER's actual content. If the loser does not address a step, use `not_covered`.
- Do not invent agreements or disagreements. If you cannot tell whether the loser agrees, use `not_covered` with a note.
- `adds` annotations MUST cite the loser's claim id. `disagrees` annotations MUST cite both sides.
</rules>

<process>
1. In <scratchpad>, score both analyses on the rubric. Pick the spine.
2. For each spine step, scan the loser for the closest semantic match. Decide: agrees, disagrees, adds, or not_covered.
3. List loser steps with no spine match in additions_from_loser.
4. Emit the JSON.
</process>

<output_format>
Reason in <scratchpad>...</scratchpad>, then emit one JSON object wrapped in <final_json>...</final_json>: scores_a {step_atomicity, citation_grounding, assumption_transparency, coherence} with integer values from 1 to 5, scores_b {...}, spine_winner in {"A","B"}, spine_rationale (2-3 sentences), claim_verdicts[] (each with claim_id, loser_position in {agrees, disagrees, not_covered, adds}, loser_note), additions_from_loser[] (each with claim, evidence[]). No content after </final_json>.
</output_format>
"""
