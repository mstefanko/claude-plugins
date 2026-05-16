package cli

import (
	"context"
	"errors"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
)

const (
	ExitSuccess           = 0
	ExitRuntimeFailure    = 1
	ExitUsage             = 2
	ExitJudgeDisagreement = 3
	ExitInterrupted       = 130
)

func ExitCode(err error, rootSignalCanceled bool) int {
	if err == nil {
		return ExitSuccess
	}
	var interrupted *apperror.InterruptedError
	if errors.As(err, &interrupted) || (rootSignalCanceled && errors.Is(err, context.Canceled)) {
		return ExitInterrupted
	}
	var usage *apperror.UsageError
	if errors.As(err, &usage) {
		return ExitUsage
	}
	var validation *apperror.ValidationError
	if errors.As(err, &validation) {
		return ExitUsage
	}
	var disagreement *apperror.JudgeDisagreementError
	if errors.As(err, &disagreement) {
		return ExitJudgeDisagreement
	}
	return ExitRuntimeFailure
}

func RenderError(streams output.Streams, err error, code int) {
	if err == nil || apperror.IsSilent(err) {
		return
	}
	if code == ExitInterrupted {
		streams.Errorf("error: interrupted\n")
		return
	}
	streams.Errorf("error: %s\n", err)
}
