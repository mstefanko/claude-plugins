package runnerenv

import "strings"

func SafeEnv(environ []string) []string {
	out := make([]string, 0, len(environ))
	for _, item := range environ {
		key := item
		if index := strings.IndexByte(item, '='); index >= 0 {
			key = item[:index]
		}
		if ShouldScrub(key) {
			continue
		}
		out = append(out, item)
	}
	return out
}

func ShouldScrub(key string) bool {
	upper := strings.ToUpper(key)
	if strings.HasPrefix(upper, "ANTHROPIC_") || strings.HasPrefix(upper, "OPENAI_") {
		return true
	}
	for _, marker := range []string{"API_KEY", "ACCESS_KEY", "PRIVATE_KEY", "SECRET", "TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER", "CREDENTIAL", "PASSPHRASE", "JWT", "SESSION", "COOKIE"} {
		if strings.Contains(upper, marker) {
			return true
		}
	}
	return false
}
