package prompt

type TrimRecord struct {
	Prompt   string   `json:"prompt"`
	Sections []string `json:"sections"`
}

type TrimResult struct {
	Text          string
	Record        *TrimRecord
	OriginalBytes int
	FinalBytes    int
}

func TrimContextToBudget(text string, maxBytes int, promptLabel string) TrimResult {
	result := TrimResult{
		Text:          text,
		OriginalBytes: len(text),
		FinalBytes:    len(text),
	}
	if len(text) <= maxBytes {
		return result
	}
	sections := []string{}
	trimmed := text
	for _, tag := range []string{"context", "background", "repo_layout"} {
		var changed bool
		trimmed, changed = clearTagInner(trimmed, tag)
		if changed {
			sections = append(sections, tag)
		}
	}
	result.Text = trimmed
	result.FinalBytes = len(trimmed)
	if len(sections) > 0 {
		result.Record = &TrimRecord{Prompt: promptLabel, Sections: sections}
	}
	return result
}

func clearTagInner(text string, tag string) (string, bool) {
	trimmed := replaceTagInner(text, tag, "")
	return trimmed, trimmed != text
}
