package commands

import (
	"errors"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runner"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type Factory interface {
	Streams() output.Streams
	BuildInfo() buildinfo.Info
	Now() time.Time
	LookupProvider(string) (string, error)
	Capabilities() *provider.CapabilityRegistry
}

func PlaceholderError(command string) error {
	return apperror.Runtimef("%s command is not implemented in bakeoff-go yet", command)
}

func WrapValidation(err error) error {
	var validation *workorder.ValidationError
	if errors.As(err, &validation) {
		return &apperror.ValidationError{Message: validation.Error(), Err: err}
	}
	return err
}

func RunnerBudgets(b workorder.Budgets) runner.Budgets {
	return runner.Budgets{
		WallClockSeconds:      b.WallClockSeconds,
		MaxOutputBytes:        b.MaxOutputBytes,
		HeartbeatSeconds:      b.HeartbeatSeconds,
		OutputCapGraceSeconds: b.OutputCapGraceSeconds,
		MaxOutputOverrunBytes: b.MaxOutputOverrunBytes,
	}
}

func MakeTickPrinter(f Factory, label string, quiet bool) func(runner.Tick) {
	if quiet {
		return nil
	}
	return func(tick runner.Tick) {
		elapsed := int(tick.Elapsed)
		wallSeconds := tick.WallSeconds
		lastOutputAge := int(tick.LastOutputAge)
		f.Streams().Errorf("[%s] %s t=%ds/%ds out=%.1fKB err=%.1fKB last=%ds\n", label, tick.Phase, elapsed, wallSeconds, float64(tick.StdoutBytes)/1024, float64(tick.StderrBytes)/1024, lastOutputAge)
	}
}
