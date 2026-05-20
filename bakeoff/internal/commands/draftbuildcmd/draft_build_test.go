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
	})
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
	})
	var validation *apperror.ValidationError
	if !errors.As(err, &validation) || !strings.Contains(err.Error(), "acceptance") {
		t.Fatalf("expected validation error mentioning acceptance, got %T %v", err, err)
	}
	if out.String() != "" || errOut.String() != "" {
		t.Fatalf("unexpected output stdout=%q stderr=%q", out.String(), errOut.String())
	}
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
