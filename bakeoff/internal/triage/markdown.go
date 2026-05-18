package triage

import (
	"fmt"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
)

func RenderTriageMarkdown(final map[string]any, caveats []string) string {
	lines := []string{
		fmt.Sprintf("# Bakeoff Triage: %v", final["run_id"]),
		"",
		"## Summary",
		"",
		fmt.Sprint(final["summary"]),
	}
	if sourceFilter, ok := sourceFilterMap(final["source_finding_filter"]); ok {
		lines = append(lines,
			"",
			"## Source Findings",
			"",
			fmt.Sprintf("- Selected: `%v`", jsonutil.IntLike(sourceFilter["included"])),
			fmt.Sprintf("- Skipped non-actionable: `%v`", jsonutil.IntLike(sourceFilter["skipped_non_actionable"])),
			fmt.Sprintf("- Skipped out-of-facet: `%v`", jsonutil.IntLike(sourceFilter["skipped_out_of_facet"])),
		)
	}
	if len(caveats) > 0 {
		lines = append(lines, "", "## Caveats")
		for _, caveat := range caveats {
			lines = append(lines, "- "+caveat)
		}
	}
	buckets := []struct {
		title string
		items []map[string]any
	}{
		{title: "Fix Now"},
		{title: "False Positives"},
		{title: "Already Fixed"},
		{title: "Needs Reproduction"},
		{title: "Defer / Product Decision"},
		{title: "Other Valid Items"},
	}
	for _, item := range triageItems(final["items"]) {
		bucket := triageMarkdownBucket(item)
		if bucket == "" {
			bucket = "Other Valid Items"
		}
		for i := range buckets {
			if buckets[i].title == bucket {
				buckets[i].items = append(buckets[i].items, item)
				break
			}
		}
	}
	for _, bucket := range buckets {
		lines = append(lines, "", "## "+bucket.title, "")
		if len(bucket.items) == 0 {
			lines = append(lines, "- None.")
			continue
		}
		for _, item := range bucket.items {
			lines = append(lines, formatTriageItem(item))
		}
	}
	lines = append(lines, "", "## Unknowns", "")
	unknowns := stringSlice(final["unknowns"])
	if len(unknowns) == 0 {
		lines = append(lines, "- None.")
	} else {
		for _, item := range unknowns {
			lines = append(lines, "- "+item)
		}
	}
	return strings.Join(lines, "\n") + "\n"
}

func triageMarkdownBucket(item map[string]any) string {
	classification, _ := item["classification"].(string)
	action, _ := item["recommended_action"].(string)
	switch {
	case action == "fix_now":
		return "Fix Now"
	case classification == "false_positive":
		return "False Positives"
	case classification == "already_fixed":
		return "Already Fixed"
	case action == "reproduce" || classification == "needs_repro" || classification == "evidence_gap":
		return "Needs Reproduction"
	case action == "document" || action == "defer" || classification == "plan_doc_drift" || classification == "product_decision":
		return "Defer / Product Decision"
	default:
		return ""
	}
}

func formatTriageItem(item map[string]any) string {
	header := fmt.Sprintf("- [%s]", jsonutil.StringValue(item["id"]))
	if classification := collapseWhitespace(jsonutil.StringValue(item["classification"])); classification != "" {
		header += " **" + classification + "**"
	}
	tokens := []string{}
	for _, field := range []struct {
		label string
		key   string
	}{
		{label: "severity", key: "severity"},
		{label: "confidence", key: "confidence"},
		{label: "action", key: "recommended_action"},
	} {
		if value := collapseWhitespace(jsonutil.StringValue(item[field.key])); value != "" {
			tokens = append(tokens, field.label+"="+value)
		}
	}
	if len(tokens) > 0 {
		header += " · " + strings.Join(tokens, " · ")
	}
	source := jsonutil.StringValue(jsonutil.FirstNonNil(item["source_finding"], item["source_finding_id"]))
	lines := []string{header}
	for _, detail := range []string{
		formatTriageDetail("Source", source),
		formatTriageDetail("Rationale", jsonutil.StringValue(item["rationale"])),
		formatTriageListDetail("Supporting evidence", item["supporting_evidence"]),
		formatTriageListDetail("Counter-evidence", item["counterevidence"]),
		formatTriageListDetail("Citation checks", item["citation_check_ids"]),
	} {
		if detail != "" {
			lines = append(lines, detail)
		}
	}
	return strings.Join(lines, "\n")
}

func formatTriageDetail(label, value string) string {
	value = collapseWhitespace(value)
	if value == "" {
		return ""
	}
	return "  " + label + ": " + value
}

func formatTriageListDetail(label string, value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case []any, []string:
		items := stringSlice(typed)
		parts := make([]string, 0, len(items))
		for _, item := range items {
			if text := collapseWhitespace(item); text != "" {
				parts = append(parts, text)
			}
		}
		if len(parts) == 0 {
			return ""
		}
		return "  " + label + ": " + strings.Join(parts, ", ")
	default:
		return formatTriageDetail(label, jsonutil.StringValue(value))
	}
}

func collapseWhitespace(value string) string {
	return strings.Join(strings.Fields(value), " ")
}

func triageItems(value any) []map[string]any {
	raw, ok := value.([]any)
	if !ok {
		return nil
	}
	items := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		if obj, ok := item.(map[string]any); ok {
			items = append(items, obj)
		}
	}
	return items
}

func stringSlice(value any) []string {
	switch raw := value.(type) {
	case []string:
		return append([]string(nil), raw...)
	case []any:
		items := make([]string, 0, len(raw))
		for _, item := range raw {
			items = append(items, fmt.Sprint(item))
		}
		return items
	default:
		return nil
	}
}

func sourceFilterMap(value any) (map[string]any, bool) {
	switch typed := value.(type) {
	case map[string]any:
		return typed, true
	case map[string]int:
		out := map[string]any{}
		for key, item := range typed {
			out[key] = item
		}
		return out, true
	default:
		return nil, false
	}
}
