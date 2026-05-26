package commands

import (
	"bytes"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
)

type sharedTestFactory struct {
	streams output.Streams
}

func (f sharedTestFactory) Streams() output.Streams {
	return f.streams
}

func (f sharedTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f sharedTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f sharedTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f sharedTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestMakeTickPrinterNotesLongQuietOnce(t *testing.T) {
	var out, errOut bytes.Buffer
	f := sharedTestFactory{streams: output.NewStreams(&out, &errOut)}
	printTick := MakeTickPrinter(f, "claude", false)

	printTick(runner.Tick{Phase: "quiet", Elapsed: 600, WallSeconds: 1200, LastOutputAge: 600})
	printTick(runner.Tick{Phase: "quiet", Elapsed: 660, WallSeconds: 1200, LastOutputAge: 660})

	text := errOut.String()
	if strings.Count(text, "provider output may be buffered until completion") != 1 {
		t.Fatalf("long quiet note should appear once:\n%s", text)
	}
}
