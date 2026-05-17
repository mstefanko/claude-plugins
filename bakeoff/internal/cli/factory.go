package cli

import (
	"os/exec"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
)

type Factory struct {
	streams        output.Streams
	buildInfo      buildinfo.Info
	now            func() time.Time
	lookupProvider func(string) (string, error)
	capabilities   *provider.CapabilityRegistry
}

func NewFactory(streams output.Streams) *Factory {
	f := &Factory{
		streams:        streams,
		buildInfo:      buildinfo.Current(),
		now:            time.Now,
		lookupProvider: exec.LookPath,
	}
	f.capabilities = provider.NewCapabilityRegistry(f.LookupProvider)
	return f
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

func (f *Factory) Capabilities() *provider.CapabilityRegistry {
	return f.capabilities
}
