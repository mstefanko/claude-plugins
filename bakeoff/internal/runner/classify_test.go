package runner

import "testing"

func TestClassifyJudgeError(t *testing.T) {
	one := 1
	zero := 0
	tests := []struct {
		name     string
		status   string
		exitCode *int
		stdout   string
		stderr   string
		want     string
	}{
		{name: "api transient", status: StatusExitError, exitCode: &one, stdout: "API Error: The socket connection was closed unexpectedly", want: "api_transient"},
		{name: "prompt too large", status: StatusExitError, exitCode: &one, stderr: "context_length exceeded", want: "prompt_too_large"},
		{name: "timeout", status: StatusTimeout, want: "timeout"},
		{name: "output cap", status: StatusOutputCap, want: "output_cap"},
		{name: "schema", status: StatusSchemaError, exitCode: &zero, stderr: "worker final_json.claims is required", want: "schema_error"},
		{name: "nonzero", status: StatusExitError, exitCode: &one, stderr: "fatal", want: "nonzero_exit"},
		{name: "parse", status: StatusExitError, exitCode: &zero, stderr: "missing final_json block", want: "parse_error"},
		{name: "unknown", status: StatusCancelled, want: "unknown"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ClassifyJudgeError(tt.status, tt.exitCode, tt.stdout, tt.stderr); got != tt.want {
				t.Fatalf("ClassifyJudgeError() = %q, want %q", got, tt.want)
			}
		})
	}
}
