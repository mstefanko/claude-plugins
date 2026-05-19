package modeldefaults

const (
	ClaudeSonnet = "sonnet"
	ClaudeOpus   = "opus"

	// Keep explicit until the Claude CLI's haiku alias behavior is verified.
	ClaudeHaiku = "claude-haiku-4-5-20251001"

	CodexDefault = "gpt-5.5"
	CodexGPT5    = "gpt-5"
)

func DoctorModelIDs() map[string]string {
	return map[string]string{
		"claude_sonnet": ClaudeSonnet,
		"claude_opus":   ClaudeOpus,
		"claude_haiku":  ClaudeHaiku,
		"codex":         CodexDefault,
		"codex_gpt5":    CodexGPT5,
	}
}
