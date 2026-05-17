package decision

import (
	"encoding/json"
	"regexp"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/artifact"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func Base(wo *workorder.WorkOrder, workerResults map[string]map[string]any) map[string]any {
	statuses := map[string]any{}
	for _, provider := range wo.Providers {
		result := workerResults[provider.ID]
		status := artifact.StatusWithoutPayload(result)
		status["stderr_path"] = "providers/" + provider.ID + "/stderr.txt"
		statuses[provider.ID] = status
	}
	return map[string]any{
		"mode":              wo.Type,
		"provider_statuses": statuses,
		"canonical_winner":  nil,
		"judge_rationale":   []string{},
		"caveats":           []string{},
	}
}

func BothFailed(wo *workorder.WorkOrder, workerResults map[string]map[string]any) map[string]any {
	out := Base(wo, workerResults)
	out["decision_kind"] = "both_failed"
	out["judge_ran"] = false
	out["canonical_winner"] = nil
	out["caveats"] = []string{"both providers failed; judge skipped"}
	return out
}

func SingleProviderOnly(wo *workorder.WorkOrder, workerResults map[string]map[string]any, survivor string) map[string]any {
	out := Base(wo, workerResults)
	failed := ""
	for _, provider := range wo.Providers {
		if provider.ID != survivor {
			failed = provider.ID
			break
		}
	}
	status := "missing_status"
	if failed != "" {
		if result, ok := workerResults[failed]; ok {
			if value, ok := result["status"].(string); ok && value != "" {
				status = value
			}
		}
	} else {
		failed = "unknown"
	}
	out["decision_kind"] = "single_provider_only"
	out["judge_ran"] = false
	out["canonical_winner"] = survivor
	out["caveats"] = []string{SingleProviderCaveat(wo.Type, survivor, failed, status)}
	return out
}

func GatherStructuredUnion(wo *workorder.WorkOrder, workerResults map[string]map[string]any, judgeResult map[string]any) (map[string]any, map[string]map[string]any, int) {
	order := map[string]string{"A": wo.Providers[0].ID, "B": wo.Providers[1].ID}
	judgeResults := map[string]map[string]any{"pass1": finalJSONMap(judgeResult)}
	out := Base(wo, workerResults)
	out["decision_kind"] = "structured_union"
	out["judge_ran"] = true
	out["order_maps"] = map[string]any{"pass1": order}
	out["canonical_winner"] = nil
	out["judge_rationale"] = []string{}
	out["caveats"] = []string{}
	if !artifact.ProviderSucceeded(judgeResult) {
		status, _ := judgeResult["status"].(string)
		out["caveats"] = []string{"gather judge failed with " + status}
		return out, judgeResults, 1
	}
	return out, judgeResults, 0
}

func ResolveCompare(base map[string]any, judgeResults map[string]map[string]any, pass1Order map[string]string, pass2Order map[string]string) map[string]any {
	pass1 := judgeResults["pass1"]
	pass2 := judgeResults["pass2"]
	out := cloneMap(base)
	out["judge_ran"] = true
	out["order_maps"] = map[string]any{"pass1": pass1Order, "pass2": pass2Order}
	out["judge_passes"] = map[string]any{
		"pass1": JudgePassSummary(pass1, pass1Order, "winner"),
		"pass2": JudgePassSummary(pass2, pass2Order, "winner"),
	}
	out["canonical_winner"] = nil
	out["judge_rationale"] = []string{rationale(pass1), rationale(pass2)}
	out["caveats"] = []string{}
	if pass1["relation"] == "consensus" && pass2["relation"] == "consensus" {
		out["decision_kind"] = "consensus"
		out["consensus_strongest"] = MergeItems(asList(pass1["consensus_strongest"]), asList(pass2["consensus_strongest"]))
		out["consensus_disagreements"] = MergeItems(asList(pass1["consensus_disagreements"]), asList(pass2["consensus_disagreements"]))
		return out
	}
	winner1 := CanonicalWinner(pass1["winner"], pass1Order)
	winner2 := CanonicalWinner(pass2["winner"], pass2Order)
	if winner1 != "" && winner1 == winner2 {
		loser1 := otherProvider(pass1Order, winner1)
		loser2 := otherProvider(pass2Order, winner1)
		out["decision_kind"] = "pick_winner"
		out["canonical_winner"] = winner1
		out["kept_from_nonwinner"] = MergeItems(AnnotateSource(asList(pass1["kept_from_nonwinner"]), loser1), AnnotateSource(asList(pass2["kept_from_nonwinner"]), loser2))
		return out
	}
	preserved := MergeItems(PreservedCompareMaterial(pass1, pass1Order), PreservedCompareMaterial(pass2, pass2Order))
	out["decision_kind"] = "tie"
	out["caveats"] = []string{"position swap did not produce a stable winner"}
	if len(preserved) > 0 {
		out["kept_from_nonwinner"] = preserved
	}
	return out
}

func ResolveAnalyze(base map[string]any, workerResults map[string]map[string]any, judgeResults map[string]map[string]any, pass1Order map[string]string, pass2Order map[string]string, providerIDs []string) map[string]any {
	pass1 := judgeResults["pass1"]
	pass2 := judgeResults["pass2"]
	spine1 := CanonicalWinner(pass1["spine_winner"], pass1Order)
	spine2 := CanonicalWinner(pass2["spine_winner"], pass2Order)
	spine := ""
	tiebreak := ""
	if spine1 != "" && spine1 == spine2 {
		spine = spine1
		tiebreak = "swap_agreement"
	} else {
		counts := map[string]int{}
		for _, id := range providerIDs {
			counts[id] = len(asList(finalJSONMap(workerResults[id])["claims"]))
		}
		if counts[providerIDs[0]] != counts[providerIDs[1]] {
			if counts[providerIDs[0]] > counts[providerIDs[1]] {
				spine = providerIDs[0]
			} else {
				spine = providerIDs[1]
			}
			tiebreak = "atomic_count"
		} else {
			spine = providerIDs[0]
			tiebreak = "position_a"
		}
	}
	chosen := pass2
	if CanonicalWinner(pass1["spine_winner"], pass1Order) == spine {
		chosen = pass1
	}
	loser := providerIDs[0]
	if loser == spine {
		loser = providerIDs[1]
	}
	out := cloneMap(base)
	out["decision_kind"] = "pick_winner"
	out["judge_ran"] = true
	out["order_maps"] = map[string]any{"pass1": pass1Order, "pass2": pass2Order}
	out["judge_passes"] = map[string]any{
		"pass1": JudgePassSummary(pass1, pass1Order, "spine_winner"),
		"pass2": JudgePassSummary(pass2, pass2Order, "spine_winner"),
	}
	out["canonical_winner"] = spine
	out["spine_tiebreak"] = tiebreak
	out["judge_rationale"] = []string{rationale(pass1), rationale(pass2)}
	out["claim_verdicts"] = valueOrList(chosen["claim_verdicts"])
	out["additions_from_loser"] = AnnotateSource(asList(chosen["additions_from_loser"]), loser)
	out["actionable_followups"] = valueOrList(chosen["actionable_followups"])
	if tiebreak == "swap_agreement" {
		out["caveats"] = []string{}
	} else {
		out["caveats"] = []string{"spine chosen by " + tiebreak + " after swap disagreement"}
	}
	return out
}

func JudgePassSummary(result map[string]any, orderMap map[string]string, verdictKey string) map[string]any {
	positional, _ := result[verdictKey].(string)
	out := map[string]any{
		"A":                 orderMap["A"],
		"B":                 orderMap["B"],
		"positional_winner": positional,
		"canonical_winner":  nil,
	}
	if canonical := CanonicalWinner(positional, orderMap); canonical != "" {
		out["canonical_winner"] = canonical
	}
	if relation, ok := result["relation"]; ok && relation != nil {
		out["relation"] = relation
	}
	return out
}

func CanonicalWinner(verdict any, orderMap map[string]string) string {
	text, _ := verdict.(string)
	if text == "A" || text == "B" {
		return orderMap[text]
	}
	return ""
}

func AnnotateSource(items []any, sourceProvider string) []any {
	out := []any{}
	for _, item := range items {
		if obj, ok := item.(map[string]any); ok {
			copy := cloneMap(obj)
			copy["source_provider"] = sourceProvider
			out = append(out, copy)
		} else {
			out = append(out, map[string]any{"claim": stringify(item), "source_provider": sourceProvider})
		}
	}
	return out
}

func PreservedCompareMaterial(result map[string]any, orderMap map[string]string) []any {
	items := asList(result["kept_from_nonwinner"])
	if len(items) == 0 {
		return nil
	}
	winner := CanonicalWinner(result["winner"], orderMap)
	source := "unknown"
	if winner != "" {
		source = otherProvider(orderMap, winner)
	}
	return AnnotateSource(items, source)
}

func MergeItems(groups ...[]any) []any {
	merged := []any{}
	seenKeys := map[string]bool{}
	seenTexts := []textSource{}
	for _, group := range groups {
		for _, item := range group {
			key := mergeItemKey(item)
			text, source := mergeItemTextAndSource(item)
			if seenKeys[key] || isNearDuplicate(text, source, seenTexts) {
				continue
			}
			seenKeys[key] = true
			if text != "" {
				seenTexts = append(seenTexts, textSource{text: text, source: source})
			}
			merged = append(merged, item)
		}
	}
	return merged
}

func SingleProviderCaveat(mode string, survivor string, failed string, status string) string {
	switch mode {
	case "gather":
		return "single_provider_only: " + failed + " " + status + "; rendering " + survivor + " findings without dedupe"
	case "compare":
		return "single_provider_only: " + failed + " " + status + "; no comparison possible - surfacing " + survivor + " result only"
	default:
		return "single_provider_only: " + failed + " " + status + "; no overlay possible - surfacing " + survivor + " analysis only"
	}
}

func finalJSONMap(result map[string]any) map[string]any {
	final, _ := result["final_json"].(map[string]any)
	if final == nil {
		return map[string]any{}
	}
	return final
}

func rationale(result map[string]any) string {
	value := result["rationale"]
	if value == nil {
		value = result["spine_rationale"]
	}
	if items, ok := value.([]any); ok {
		parts := []string{}
		for _, item := range items {
			parts = append(parts, stringify(item))
		}
		return strings.Join(parts, " ")
	}
	return stringify(value)
}

func otherProvider(orderMap map[string]string, winner string) string {
	for _, provider := range orderMap {
		if provider != winner {
			return provider
		}
	}
	return "unknown"
}

func valueOrList(value any) any {
	if value == nil {
		return []any{}
	}
	return value
}

func asList(value any) []any {
	items, ok := value.([]any)
	if !ok {
		return []any{}
	}
	return items
}

func cloneMap(in map[string]any) map[string]any {
	out := map[string]any{}
	for key, value := range in {
		out[key] = value
	}
	return out
}

func stringify(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(fmtAny(value), "\n", " "), "  ", " "))
}

func fmtAny(value any) string {
	data, err := json.Marshal(value)
	if err == nil {
		return string(data)
	}
	return ""
}

type textSource struct {
	text   string
	source string
}

func mergeItemKey(item any) string {
	if obj, ok := item.(map[string]any); ok {
		text, source := mergeItemTextAndSource(obj)
		data, _ := json.Marshal(map[string]any{"text": normalizeMergeText(text), "source": source})
		return string(data)
	}
	return normalizeMergeText(stringify(item))
}

func mergeItemTextAndSource(item any) (string, string) {
	if obj, ok := item.(map[string]any); ok {
		text := firstString(obj["claim"], obj["description"], obj["loser_note"], stringify(obj))
		source, _ := obj["source_provider"].(string)
		return text, source
	}
	return stringify(item), ""
}

func isNearDuplicate(text string, source string, seen []textSource) bool {
	if text == "" {
		return false
	}
	for _, existing := range seen {
		if source != existing.source {
			continue
		}
		if !sameStringSet(numericTokens(text), numericTokens(existing.text)) {
			continue
		}
		if tokenSimilarity(text, existing.text) >= 0.95 {
			return true
		}
	}
	return false
}

func tokenSimilarity(left string, right string) float64 {
	leftTokens := mergeTokens(left)
	rightTokens := mergeTokens(right)
	if len(leftTokens) == 0 || len(rightTokens) == 0 {
		return 0
	}
	union := map[string]bool{}
	intersection := 0
	for token := range leftTokens {
		union[token] = true
		if rightTokens[token] {
			intersection++
		}
	}
	for token := range rightTokens {
		union[token] = true
	}
	return float64(intersection) / float64(len(union))
}

func mergeTokens(text string) map[string]bool {
	stopwords := map[string]bool{"a": true, "an": true, "are": true, "can": true, "is": true, "s": true, "the": true, "to": true, "via": true, "while": true, "with": true}
	tokens := map[string]bool{}
	for _, token := range strings.Fields(normalizeMergeText(text)) {
		if !stopwords[token] {
			tokens[token] = true
		}
	}
	return tokens
}

var numberRE = regexp.MustCompile(`\d+(?:\.\d+)?`)
var parenRE = regexp.MustCompile(`\([AB]/R-\d{3}\)`)
var nonAlphaRE = regexp.MustCompile(`[^a-z0-9]+`)

func numericTokens(text string) map[string]bool {
	out := map[string]bool{}
	for _, token := range numberRE.FindAllString(text, -1) {
		out[token] = true
	}
	return out
}

func normalizeMergeText(text string) string {
	text = parenRE.ReplaceAllString(strings.ToLower(text), "")
	text = nonAlphaRE.ReplaceAllString(text, " ")
	return strings.Join(strings.Fields(text), " ")
}

func sameStringSet(left map[string]bool, right map[string]bool) bool {
	if len(left) != len(right) {
		return false
	}
	for key := range left {
		if !right[key] {
			return false
		}
	}
	return true
}

func firstString(values ...any) string {
	for _, value := range values {
		if text, ok := value.(string); ok && text != "" {
			return text
		}
	}
	return ""
}
