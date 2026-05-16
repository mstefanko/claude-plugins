package cli

import (
	"bytes"
	"context"
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
	if runErr == nil || !strings.Contains(runErr.Error(), "doctor command is not implemented") {
		t.Fatalf("placeholder error = %v", runErr)
	}
}
