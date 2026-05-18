package runresult

import (
	"fmt"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
)

func InternalError(err error) map[string]any {
	message := fmt.Sprintf("internal provider task error: %T: %v", err, err)
	stderrBytes := len([]byte(message))
	return map[string]any{
		"status":                runner.StatusExitError,
		"exit_code":             nil,
		"wall_seconds":          0,
		"output_bytes":          0,
		"stdout_bytes":          0,
		"stderr_bytes":          stderrBytes,
		"stdout_observed_bytes": 0,
		"stderr_observed_bytes": stderrBytes,
		"stdout_truncated":      false,
		"stderr_truncated":      false,
		"io":                    map[string]any{"stdout_bytes": 0, "stderr_bytes": stderrBytes, "stdout_observed_bytes": 0, "stderr_observed_bytes": stderrBytes, "total_observed_bytes": stderrBytes},
		"stdout":                "",
		"stderr":                message,
		"final_json":            nil,
	}
}
