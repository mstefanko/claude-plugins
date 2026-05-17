package cli

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
)

func TestRootHelpAndPlaceholder(t *testing.T) {
	var out, errOut bytes.Buffer
	f := NewFactory(output.NewStreams(&out, &errOut))
	root := NewRootCommand(f)
	root.SetOut(&out)
	root.SetErr(&errOut)
	root.SetArgs([]string{"--help"})
	if err := root.ExecuteContext(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "init") || !strings.Contains(out.String(), "research") {
		t.Fatalf("help output missing expected commands:\n%s", out.String())
	}

	out.Reset()
	errOut.Reset()
	root = NewRootCommand(f)
	root.SetOut(&out)
	root.SetErr(&errOut)
	root.SetArgs([]string{"doctor", "--skip-auth-probe"})
	runErr := root.ExecuteContext(context.Background())
	if runErr != nil {
		t.Fatalf("doctor returned error = %v", runErr)
	}
}

func TestDoctorFailureReturnsErrorAfterJSON(t *testing.T) {
	var out, errOut bytes.Buffer
	f := NewFactory(output.NewStreams(&out, &errOut))
	f.lookupProvider = func(string) (string, error) {
		return "", errors.New("missing")
	}
	root := NewRootCommand(f)
	root.SetOut(&out)
	root.SetErr(&errOut)
	root.SetArgs([]string{"doctor", "--skip-auth-probe", "--json"})

	runErr := root.ExecuteContext(context.Background())
	if runErr == nil {
		t.Fatal("doctor returned nil error for failed readiness report")
	}
	if !strings.Contains(out.String(), `"status": "failed"`) {
		t.Fatalf("doctor JSON missing failed status:\n%s", out.String())
	}
	if errOut.String() != "" {
		t.Fatalf("doctor should not render an extra command error before root handling, got %q", errOut.String())
	}
}
