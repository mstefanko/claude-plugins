package runner

import "testing"

func TestClassifyFailure(t *testing.T) {
	tests := []struct {
		name   string
		status string
		stdout string
		stderr string
		want   string
	}{
		{name: "missing provider status", status: StatusMissingProvider, want: "missing_provider"},
		{name: "timeout status", status: StatusTimeout, want: "timeout"},
		{name: "output cap status", status: StatusOutputCap, want: "output_cap"},
		{name: "schema status", status: StatusSchemaError, want: "schema_error"},
		{name: "timeout text", status: StatusExitError, stderr: "provider timed out waiting for response", want: "timeout"},
		{name: "prompt too large context", status: StatusExitError, stderr: "context_length exceeded", want: "prompt_too_large"},
		{name: "prompt guard", status: StatusExitError, stderr: "prompt too large: 1049001 bytes exceeds 1000000 byte limit", want: "prompt_too_large"},
		{name: "auth exact type", status: StatusExitError, stderr: "AuthenticationError: invalid api key", want: "auth_or_permission"},
		{name: "auth http paired", status: StatusExitError, stderr: "HTTP 403 permission denied for this model", want: "auth_or_permission"},
		{name: "rate limit", status: StatusExitError, stderr: "rate_limit_error: retry later", want: "rate_or_quota_limited"},
		{name: "quota exceeded", status: StatusExitError, stderr: "You exceeded your current quota", want: "rate_or_quota_limited"},
		{name: "api transient http", status: StatusExitError, stderr: "HTTP 503 service unavailable", want: "api_transient"},
		{name: "api transient network", status: StatusExitError, stdout: "API Error: The socket connection was closed unexpectedly", want: "api_transient"},
		{name: "final json parse text", status: StatusExitError, stderr: "stdout is missing a <final_json>...</final_json> block", want: "schema_error"},
		{name: "ambiguous nonzero", status: StatusExitError, stderr: "fatal", want: ""},
		{name: "cancelled stays unclassified", status: StatusCancelled, stderr: "provider timed out after cancellation", want: ""},
		{name: "billing left unclassified", status: StatusExitError, stderr: "billing_error: payment method required", want: ""},
		{name: "quota policy left unclassified", status: StatusExitError, stderr: "quota policy applies to monthly_active_users", want: ""},
		{name: "forbidden without permission wording", status: StatusExitError, stderr: "forbidden content was filtered", want: ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ClassifyFailure(tt.status, tt.stdout, tt.stderr); got != tt.want {
				t.Fatalf("ClassifyFailure() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestClassifyJudgeErrorDelegates(t *testing.T) {
	one := 1
	if got := ClassifyJudgeError(StatusExitError, &one, "", "rate_limit_error"); got != "rate_or_quota_limited" {
		t.Fatalf("ClassifyJudgeError() = %q, want rate_or_quota_limited", got)
	}
}

func TestClassifyFailureWithStatsNoOutputWedge(t *testing.T) {
	got := ClassifyFailureWithStats(StatusExitError, "", "", FailureStats{
		WallSeconds:           120,
		QuietThresholdSeconds: 20,
	})
	if got != "wedged_no_output" {
		t.Fatalf("ClassifyFailureWithStats() = %q, want wedged_no_output", got)
	}
	quick := ClassifyFailureWithStats(StatusExitError, "", "", FailureStats{
		WallSeconds:           1,
		QuietThresholdSeconds: 20,
	})
	if quick != "" {
		t.Fatalf("quick no-output exit should remain unclassified, got %q", quick)
	}
	defaultThreshold := ClassifyFailureWithStats(StatusExitError, "", "", FailureStats{
		WallSeconds: DefaultNoOutputWedgeSeconds,
	})
	if defaultThreshold != "wedged_no_output" {
		t.Fatalf("default no-output threshold = %q, want wedged_no_output", defaultThreshold)
	}
}
