package prompt

import (
	"strings"
	"testing"
)

func TestTrimContextToBudgetNoopsUnderBudget(t *testing.T) {
	text := "<context>\nsmall\n</context>"
	result := TrimContextToBudget(text, len(text), "worker:claude")
	if result.Text != text || result.Record != nil {
		t.Fatalf("result = %#v", result)
	}
}

func TestTrimContextToBudgetClearsContextTags(t *testing.T) {
	text := "<context>\n" + strings.Repeat("x", 20) + "\n</context>"
	result := TrimContextToBudget(text, 10, "worker:claude")
	if result.Text != "<context>\n</context>" {
		t.Fatalf("trimmed text = %q", result.Text)
	}
	if result.Record == nil || result.Record.Prompt != "worker:claude" || strings.Join(result.Record.Sections, ",") != "context" {
		t.Fatalf("record = %#v", result.Record)
	}
	if result.Record.OriginalBytes != len(text) || result.Record.FinalBytes != len(result.Text) {
		t.Fatalf("record byte counts = %#v, result = %#v", result.Record, result)
	}
}

func TestTrimContextToBudgetRecordsExactBackgroundAndRepoLayoutSections(t *testing.T) {
	text := "<background>\n" + strings.Repeat("b", 20) + "\n</background>\n<repo_layout>\n" + strings.Repeat("r", 20) + "\n</repo_layout>"
	result := TrimContextToBudget(text, 10, "judge:pass1")
	if !strings.Contains(result.Text, "<background>\n</background>") || !strings.Contains(result.Text, "<repo_layout>\n</repo_layout>") {
		t.Fatalf("trimmed text = %q", result.Text)
	}
	if result.Record == nil || strings.Join(result.Record.Sections, ",") != "background,repo_layout" {
		t.Fatalf("record = %#v", result.Record)
	}
}

func TestTrimContextToBudgetIgnoresMalformedTags(t *testing.T) {
	text := "<context>\n" + strings.Repeat("x", 20)
	result := TrimContextToBudget(text, 10, "worker:claude")
	if result.Text != text || result.Record != nil {
		t.Fatalf("result = %#v", result)
	}
}

func TestTrimContextToBudgetMayRemainOversizedAfterTrimming(t *testing.T) {
	text := "<context>\n" + strings.Repeat("x", 20) + "\n</context>\n<rules>" + strings.Repeat("y", 20) + "</rules>"
	result := TrimContextToBudget(text, 10, "worker:claude")
	if result.FinalBytes <= 10 {
		t.Fatalf("required content should remain over budget: %#v", result)
	}
	if result.Record == nil || strings.Join(result.Record.Sections, ",") != "context" {
		t.Fatalf("record = %#v", result.Record)
	}
}
