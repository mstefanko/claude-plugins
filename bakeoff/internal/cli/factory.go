package cli

import (
	"os/exec"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
)

type Factory struct {
	streams        output.Streams
	buildInfo      buildinfo.Info
	now            func() time.Time
	lookupProvider func(string) (string, error)
}

func NewFactory(streams output.Streams) *Factory {
	return &Factory{
		streams:        streams,
		buildInfo:      buildinfo.Current(),
		now:            time.Now,
		lookupProvider: exec.LookPath,
	}
}

func (f *Factory) Streams() output.Streams {
	return f.streams
}

func (f *Factory) BuildInfo() buildinfo.Info {
	return f.buildInfo
}

func (f *Factory) Now() time.Time {
	return f.now()
}

func (f *Factory) LookupProvider(name string) (string, error) {
	return f.lookupProvider(name)
}
