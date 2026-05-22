package commands

import (
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/prompt"
)

func LogPromptTrim(f Factory, result prompt.TrimResult) {
	if result.Record == nil {
		return
	}
	f.Streams().Errorf(
		"prompt_trim: prompt=%s dropped=%s original_bytes=%d final_bytes=%d\n",
		result.Record.Prompt,
		strings.Join(result.Record.Sections, ","),
		result.OriginalBytes,
		result.FinalBytes,
	)
}

func AttachPromptTrim(decision map[string]any, records []prompt.TrimRecord) {
	if len(records) == 0 {
		return
	}
	dropped := make([]map[string]any, 0, len(records))
	for _, record := range records {
		if len(record.Sections) == 0 {
			continue
		}
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
