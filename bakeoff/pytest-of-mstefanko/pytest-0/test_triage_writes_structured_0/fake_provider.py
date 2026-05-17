
import json, os, pathlib, sys
prompt = sys.stdin.read()
name = os.environ.get("BAKEOFF_FAKE_PROVIDER_NAME", pathlib.Path(sys.argv[0]).name)
fail_providers = []
fail_judge = False
repair_providers = []
judge_mode = 'gather'
triage_source_id = None
compare_scores_a = {"evidence":5,"coherence":5,"tradeoff_honesty":5,"rebuttals":5}
compare_scores_b = {"evidence":4,"coherence":4,"tradeoff_honesty":4,"rebuttals":4}
analyze_scores_a = {"step_atomicity":5,"citation_grounding":5,"assumption_transparency":5,"coherence":5}
analyze_scores_b = {"step_atomicity":4,"citation_grounding":4,"assumption_transparency":4,"coherence":4}

def emit(obj):
    print("<scratchpad>ok</scratchpad>")
    print("<final_json>" + json.dumps(obj) + "</final_json>")

if "--version" in sys.argv:
    print(name + " fake 1.0")
elif name in fail_providers:
    print("provider failed before final json", file=sys.stderr)
    sys.exit(9)
elif fail_judge and ("deduplication and conflict-flagging judge" in prompt or "pairwise judge" in prompt or "synthesis judge" in prompt):
    print("judge failed before final json", file=sys.stderr)
    sys.exit(9)
elif name in repair_providers and "BAKEOFF_FORMAT_RETRY_V1" not in prompt:
    emit({"status":"complete","claims":[{"id":"R-001","finding":name + " malformed claim"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]})
elif "evidence-grounded triage of a Bakeoff report" in prompt:
    if triage_source_id is None:
        emit({"schema_version":1,"status":"complete","summary":"no selected findings","items":[],"unknowns":[]})
    else:
        emit({"schema_version":1,"status":"complete","summary":"checked","items":[{"id":"T-001","source_finding_id":triage_source_id,"source_finding":"Fake merged claim","classification":"real_issue","severity":"medium","confidence":"high","supporting_evidence":["src/fake.py:1"],"counterevidence":[],"citation_check_ids":[],"recommended_action":"fix_now","rationale":"actionable"}],"unknowns":[]})
elif "deduplication and conflict-flagging judge" in prompt:
    emit({"merged_claims":[{"claim":"Fake merged claim","evidence":["fake:1"],"sources":["A","B"],"confidence":"high"}],"conflicts":[],"unknowns_union":[]})
elif "pairwise judge" in prompt:
    winner = "B" if judge_mode == "compare_always_b" else "tie" if judge_mode == "compare_tie" else "A"
    emit({"relation":"compare","scores_a":compare_scores_a,"scores_b":compare_scores_b,"winner":winner,"rationale":"position " + str(winner) + " looked better","kept_from_nonwinner":[{"claim":"useful material from loser"}],"consensus_strongest":[],"consensus_disagreements":[]})
elif "synthesis judge" in prompt:
    spine_winner = "B" if judge_mode == "analyze_always_b" else "A"
    emit({"scores_a":analyze_scores_a,"scores_b":analyze_scores_b,"spine_winner":spine_winner,"spine_rationale":spine_winner + " is clearer","claim_verdicts":[],"additions_from_loser":[]})
elif "comparison question" in prompt:
    emit({"status":"complete","position":name + " position","claims":[{"id":"R-001","claim":name + " claim","evidence":["fake:1"],"confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]})
else:
    emit({"status":"complete","claims":[{"id":"R-001","claim":name + " claim","evidence":["fake:1"],"confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]})
