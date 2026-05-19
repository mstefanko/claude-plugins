package runner

import "strings"

func ClassifyJudgeError(status string, exitCode *int, stdout string, stderr string) string {
	text := strings.ToLower(stdout + "\n" + stderr)
	switch {
	case strings.Contains(text, "socket connection was closed unexpectedly"),
		strings.Contains(text, "connection error"),
		strings.Contains(text, "http 500"),
		strings.Contains(text, "http 502"),
		strings.Contains(text, "http 503"),
		strings.Contains(text, "http 504"),
		strings.Contains(text, "status 500"),
		strings.Contains(text, "status 502"),
		strings.Contains(text, "status 503"),
		strings.Contains(text, "status 504"),
		strings.Contains(text, "internal server error"),
		strings.Contains(text, "bad gateway"),
		strings.Contains(text, "service unavailable"),
		strings.Contains(text, "gateway timeout"):
		return "api_transient"
	case strings.Contains(text, "context_length"),
		strings.Contains(text, "prompt is too long"),
		strings.Contains(text, "max_tokens_exceeded"):
		return "prompt_too_large"
	case status == StatusTimeout || strings.Contains(text, "timed out") || strings.Contains(text, "timeout"):
		return "timeout"
	case status == StatusOutputCap:
		return "output_cap"
	case status == StatusSchemaError:
		return "schema_error"
	case exitCode != nil && *exitCode != 0:
		return "nonzero_exit"
	case exitCode != nil && *exitCode == 0 && strings.Contains(text, "final_json"):
		return "parse_error"
	default:
		return "unknown"
	}
}
