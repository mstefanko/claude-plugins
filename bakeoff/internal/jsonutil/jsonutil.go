package jsonutil

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
)

func StringValue(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprint(value)
}

func BoolValue(value any) bool {
	if typed, ok := value.(bool); ok {
		return typed
	}
	return false
}

func IntValue(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case json.Number:
		if n, err := typed.Int64(); err == nil {
			return int(n)
		}
		if n, err := strconv.ParseFloat(string(typed), 64); err == nil {
			return int(n)
		}
	}
	return 0
}

func Int64Value(value any) int64 {
	switch typed := value.(type) {
	case int64:
		return typed
	case int:
		return int64(typed)
	case float64:
		return int64(typed)
	case json.Number:
		if n, err := typed.Int64(); err == nil {
			return n
		}
		if n, err := strconv.ParseFloat(string(typed), 64); err == nil {
			return int64(n)
		}
	}
	return 0
}

func NumberValue(value any) float64 {
	switch typed := value.(type) {
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float64:
		return typed
	case json.Number:
		if n, err := strconv.ParseFloat(string(typed), 64); err == nil {
			return n
		}
	}
	return 0
}

func ListValue(value any) []any {
	if items, ok := value.([]any); ok {
		return items
	}
	if items, ok := value.([]string); ok {
		out := make([]any, len(items))
		for i, item := range items {
			out[i] = item
		}
		return out
	}
	return []any{}
}

func ListStrings(value any) []string {
	switch typed := value.(type) {
	case []string:
		return append([]string(nil), typed...)
	case []any:
		out := make([]string, 0, len(typed))
		for _, item := range typed {
			out = append(out, fmt.Sprint(item))
		}
		return out
	default:
		return []string{}
	}
}

func FirstNonNil(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}

func IntLike(value any) any {
	switch typed := value.(type) {
	case float64:
		if typed == math.Trunc(typed) {
			return int(typed)
		}
	case json.Number:
		if n, err := typed.Int64(); err == nil {
			return n
		}
	}
	return value
}

func FinalJSONMap(result map[string]any) map[string]any {
	final, _ := result["final_json"].(map[string]any)
	if final == nil {
		return map[string]any{}
	}
	return final
}
