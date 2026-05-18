package jsonutil

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestValues(t *testing.T) {
	if got := StringValue(12); got != "12" {
		t.Fatalf("StringValue = %q", got)
	}
	if !BoolValue(true) || BoolValue("true") {
		t.Fatalf("BoolValue did not preserve existing semantics")
	}
	if got := IntValue(json.Number("12")); got != 12 {
		t.Fatalf("IntValue(json.Number) = %d", got)
	}
	if got := Int64Value(12.9); got != 12 {
		t.Fatalf("Int64Value(float64) = %d", got)
	}
	if got := NumberValue(json.Number("1.5")); got != 1.5 {
		t.Fatalf("NumberValue(json.Number) = %v", got)
	}
	if got := ListValue([]string{"a", "b"}); !reflect.DeepEqual(got, []any{"a", "b"}) {
		t.Fatalf("ListValue = %#v", got)
	}
	if got := ListStrings([]any{"a", 2}); !reflect.DeepEqual(got, []string{"a", "2"}) {
		t.Fatalf("ListStrings = %#v", got)
	}
	if got := FirstNonNil(nil, "x"); got != "x" {
		t.Fatalf("FirstNonNil = %#v", got)
	}
	if got := IntLike(2.0); got != 2 {
		t.Fatalf("IntLike = %#v", got)
	}
	final := FinalJSONMap(map[string]any{"final_json": map[string]any{"ok": true}})
	if !reflect.DeepEqual(final, map[string]any{"ok": true}) {
		t.Fatalf("FinalJSONMap = %#v", final)
	}
}
