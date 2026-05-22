package runnerenv

import (
	"reflect"
	"testing"
)

func TestShouldScrub(t *testing.T) {
	for _, key := range []string{"ANTHROPIC_API_KEY", "OPENAI_ORG", "GEMINI_API_KEY", "GOOGLE_PROJECT", "GITHUB_TOKEN", "COPILOT_AUTH", "SERVICE_API_KEY", "AWS_ACCESS_KEY_ID", "SSH_PRIVATE_KEY", "APP_SECRET", "SESSION_TOKEN", "DB_PASSWORD", "HTTP_AUTHORIZATION", "BEARER_VALUE", "GOOGLE_APPLICATION_CREDENTIALS", "SSH_PASSPHRASE", "APP_JWT", "SESSION_ID", "COOKIE_JAR"} {
		if !ShouldScrub(key) {
			t.Fatalf("ShouldScrub(%q) = false", key)
		}
	}
	for _, key := range []string{"PATH", "HOME", "CLAUDE_PLUGIN_ROOT", "OPENED_BY_TEST"} {
		if ShouldScrub(key) {
			t.Fatalf("ShouldScrub(%q) = true", key)
		}
	}
}

func TestSafeEnv(t *testing.T) {
	got := SafeEnv([]string{"PATH=/bin", "ANTHROPIC_API_KEY=secret", "HOME=/tmp"})
	want := []string{"PATH=/bin", "HOME=/tmp"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("SafeEnv = %#v", got)
	}
}
