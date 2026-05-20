package draftbuildcmd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type draftBuildTestFactory struct {
	streams output.Streams
}

func (f draftBuildTestFactory) Streams() output.Streams {
	return f.streams
}

func (f draftBuildTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f draftBuildTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f draftBuildTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f draftBuildTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestRunDraftBuildPrintsValidatedJSONOnly(t *testing.T) {
	root := t.TempDir()
	t.Chdir(root)
	var out, errOut bytes.Buffer
	f := draftBuildTestFactory{streams: output.NewStreams(&out, &errOut)}

	err := runDraftBuild(context.Background(), f, &DraftBuildOptions{
		ID:         "draft-build-json",
		Goal:       "Print a draft build work order.",
		Acceptance: []string{"The emitted JSON validates."},
		Scopes:     []string{"internal/commands/draftbuildcmd"},
		Gates:      []string{"tests=go test ./internal/commands/draftbuildcmd"},
	}, []workorder.GateDraft{{ID: "tests", Command: "go test ./internal/commands/draftbuildcmd"}})
	if err != nil {
		t.Fatal(err)
	}
	if errOut.String() != "" {
		t.Fatalf("stderr = %q", errOut.String())
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("draft-build should not write files, found %#v", entries)
	}
	obj := decodeDraftOutput(t, out.String())
	if _, err := workorder.Validate(obj); err != nil {
		t.Fatalf("printed JSON did not validate: %v\n%s", err, out.String())
	}
}

func TestRunDraftBuildInvalidInputSurfacesValidationError(t *testing.T) {
	var out, errOut bytes.Buffer
	f := draftBuildTestFactory{streams: output.NewStreams(&out, &errOut)}

	err := runDraftBuild(context.Background(), f, &DraftBuildOptions{
		ID:     "missing-acceptance",
		Goal:   "Reject missing acceptance.",
		Scopes: []string{"internal/commands/draftbuildcmd"},
		Gates:  []string{"tests=go test ./internal/commands/draftbuildcmd"},
	}, []workorder.GateDraft{{ID: "tests", Command: "go test ./internal/commands/draftbuildcmd"}})
	var validation *apperror.ValidationError
	if !errors.As(err, &validation) || !strings.Contains(err.Error(), "acceptance") {
		t.Fatalf("expected validation error mentioning acceptance, got %T %v", err, err)
	}
	if out.String() != "" || errOut.String() != "" {
		t.Fatalf("unexpected output stdout=%q stderr=%q", out.String(), errOut.String())
	}
}

func TestParseGateFlags(t *testing.T) {
	t.Run("rejects missing separator", func(t *testing.T) {
		_, err := parseGateFlags([]string{"foo"})
		if err == nil || !strings.Contains(err.Error(), "<id>=<command>") {
			t.Fatalf("expected missing separator error, got %v", err)
		}
	})
	t.Run("rejects whitespace command", func(t *testing.T) {
		_, err := parseGateFlags([]string{"tests=   "})
		if err == nil || !strings.Contains(err.Error(), "command must be non-empty") {
			t.Fatalf("expected empty command error, got %v", err)
		}
	})
	t.Run("splits on first equals", func(t *testing.T) {
		gates, err := parseGateFlags([]string{"tests=go test -count=1"})
		if err != nil {
			t.Fatal(err)
		}
		if len(gates) != 1 || gates[0].ID != "tests" || gates[0].Command != "go test -count=1" {
			t.Fatalf("gates = %#v", gates)
		}
	})
	t.Run("rejects duplicate ids", func(t *testing.T) {
		_, err := parseGateFlags([]string{"tests=go test ./...", " tests = go test ./internal/..."})
		if err == nil || !strings.Contains(err.Error(), `--gate[1] id "tests" duplicates --gate[0]`) {
			t.Fatalf("expected duplicate id error, got %v", err)
		}
	})
}

func decodeDraftOutput(t *testing.T, text string) map[string]any {
	t.Helper()
	decoder := json.NewDecoder(strings.NewReader(text))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		t.Fatal(err)
	}
	obj, ok := value.(map[string]any)
	if !ok {
		t.Fatalf("decoded output as %T, want object", value)
	}
	return obj
}
