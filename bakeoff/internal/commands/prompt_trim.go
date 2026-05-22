package commands

import (
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
)

func LogPromptTrim(f Factory, result prompt.TrimResult) {
	LogPromptTrimRecords(f, TrimRecords(result))
}

func LogPromptTrimRecords(f Factory, records []prompt.TrimRecord) {
	for _, record := range records {
		logPromptTrimRecord(f, record)
	}
}

func logPromptTrimRecord(f Factory, record prompt.TrimRecord) {
	if len(record.Sections) == 0 {
		return
	}
	f.Streams().Errorf(
		"prompt_trim: prompt=%s dropped=%s original_bytes=%d final_bytes=%d\n",
		record.Prompt,
		strings.Join(record.Sections, ","),
		record.OriginalBytes,
		record.FinalBytes,
	)
}

func AttachPromptTrim(decision map[string]any, records []prompt.TrimRecord) {
	if len(records) == 0 {
		return
	}
	dropped := make([]map[string]any, 0, len(records))
	seen := map[string]struct{}{}
	for _, record := range records {
		// TrimContextToBudget never emits empty sections, but keep this tolerant
		// because tests and future callers may construct records by hand.
		if len(record.Sections) == 0 {
			continue
		}
		key := record.Prompt + "\x00" + strings.Join(record.Sections, "\x00")
		if _, exists := seen[key]; exists {
			continue
		}
		seen[key] = struct{}{}
		dropped = append(dropped, map[string]any{
			"prompt":   record.Prompt,
			"sections": append([]string(nil), record.Sections...),
		})
	}
	if len(dropped) == 0 {
		return
	}
	decision["prompt_trim"] = map[string]any{"dropped": dropped}
}

func TrimRecords(result prompt.TrimResult) []prompt.TrimRecord {
	if result.Record == nil {
		return nil
	}
	return []prompt.TrimRecord{*result.Record}
}
