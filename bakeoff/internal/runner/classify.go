package runner

import "strings"

func ClassifyFailure(status string, exitCode *int, stdout string, stderr string) string {
	_ = exitCode
	text := strings.ToLower(stdout + "\n" + stderr)
	switch {
	case status == StatusMissingProvider:
		return "missing_provider"
	case status == StatusTimeout:
		return "timeout"
	case status == StatusOutputCap:
		return "output_cap"
	case status == StatusSchemaError:
		return "schema_error"
	case status == StatusCancelled:
		return ""
	case strings.Contains(text, "timeout_error"),
		strings.Contains(text, "apitimeouterror"),
		strings.Contains(text, "api timeout"),
		strings.Contains(text, "timed out"):
		return "timeout"
	case strings.Contains(text, "context_length"),
		strings.Contains(text, "maximum context"),
		strings.Contains(text, "prompt is too long"),
		strings.Contains(text, "input too large"),
		strings.Contains(text, "prompt too large:"),
		strings.Contains(text, "max_tokens_exceeded"),
		strings.Contains(text, "request_too_large"):
		return "prompt_too_large"
	case hasAny(text,
		"authentication_error",
		"authenticationerror",
		"permission_error",
		"permissiondeniederror",
		"invalid authentication",
		"incorrect api key",
		"invalid api key",
		"not authenticated",
	) || ((hasHTTPStatus(text, "401", "403") || hasStandaloneCode(text, "401", "403")) && hasAuthPermissionWording(text)):
		return "auth_or_permission"
	case hasAny(text,
		"rate_limit_error",
		"ratelimiterror",
		"rate limit",
		"current quota",
		"quota",
		"usage limit",
		"insufficient credits",
	) || hasHTTPStatus(text, "429") || hasStandaloneCode(text, "429"):
		return "rate_or_quota_limited"
	case hasHTTPStatus(text, "500", "502", "503", "504", "529") ||
		hasAny(text,
			"api_error",
			"overloaded_error",
			"apiconnectionerror",
			"internal server error",
			"bad gateway",
			"service unavailable",
			"gateway timeout",
			"connection reset",
			"socket connection was closed",
		):
		return "api_transient"
	case clearFinalJSONError(text):
		return "schema_error"
	default:
		return ""
	}
}

func ClassifyJudgeError(status string, exitCode *int, stdout string, stderr string) string {
	return ClassifyFailure(status, exitCode, stdout, stderr)
}

func hasAny(text string, needles ...string) bool {
	for _, needle := range needles {
		if strings.Contains(text, needle) {
			return true
		}
	}
	return false
}

func hasHTTPStatus(text string, codes ...string) bool {
	for _, code := range codes {
		if strings.Contains(text, "http "+code) ||
			strings.Contains(text, "http status "+code) ||
			strings.Contains(text, "httperror "+code) ||
			strings.Contains(text, "status "+code) ||
			strings.Contains(text, "status_code="+code) ||
			strings.Contains(text, "statuscode="+code) {
			return true
		}
	}
	return false
}

func hasStandaloneCode(text string, codes ...string) bool {
	for _, code := range codes {
		for start := 0; start < len(text); {
			index := strings.Index(text[start:], code)
			if index < 0 {
				break
			}
			index += start
			beforeAlphaNum := index > 0 && isASCIIAlphaNum(text[index-1])
			after := index + len(code)
			afterAlphaNum := after < len(text) && isASCIIAlphaNum(text[after])
			if !beforeAlphaNum && !afterAlphaNum {
				return true
			}
			start = after
		}
	}
	return false
}

func isASCIIAlphaNum(value byte) bool {
	return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'z')
}

func hasAuthPermissionWording(text string) bool {
	return hasAny(text,
		"auth",
		"api key",
		"permission",
		"credential",
		"unauthorized",
		"forbidden",
	)
}

func clearFinalJSONError(text string) bool {
	if !strings.Contains(text, "final_json") {
		return false
	}
	return hasAny(text,
		"missing",
		"valid",
		"decode",
		"parse",
		"schema",
		"required",
		"validation",
		"must",
	)
}
