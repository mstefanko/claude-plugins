package cli

import (
	"bytes"
	"context"
	"errors"
	"testing"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
)

func TestExitCodeMapping(t *testing.T) {
	tests := []struct {
		name     string
		err      error
		signaled bool
		want     int
	}{
		{name: "success", want: 0},
		{name: "usage", err: &apperror.UsageError{Message: "bad flags"}, want: 2},
		{name: "validation", err: &apperror.ValidationError{Message: "bad work order"}, want: 2},
		{name: "runtime", err: &apperror.RuntimeError{Message: "boom"}, want: 1},
		{name: "unclassified", err: errors.New("boom"), want: 1},
		{name: "judge disagreement", err: &apperror.JudgeDisagreementError{}, want: 3},
		{name: "interrupted", err: &apperror.InterruptedError{}, want: 130},
		{name: "context canceled by signal", err: context.Canceled, signaled: true, want: 130},
		{name: "internal context canceled", err: context.Canceled, want: 1},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ExitCode(tt.err, tt.signaled); got != tt.want {
				t.Fatalf("ExitCode() = %d, want %d", got, tt.want)
			}
		})
	}
}

func TestRenderError(t *testing.T) {
	var errBuf bytes.Buffer
	streams := output.NewStreams(&bytes.Buffer{}, &errBuf)
	RenderError(streams, &apperror.RuntimeError{Message: "boom"}, 1)
	if got, want := errBuf.String(), "error: boom\n"; got != want {
		t.Fatalf("stderr = %q, want %q", got, want)
	}
	errBuf.Reset()
	RenderError(streams, context.Canceled, 130)
	if got, want := errBuf.String(), "error: interrupted\n"; got != want {
		t.Fatalf("stderr = %q, want %q", got, want)
	}
	errBuf.Reset()
	RenderError(streams, &apperror.SilentError{Err: errors.New("hidden")}, 1)
	if got := errBuf.String(); got != "" {
		t.Fatalf("silent stderr = %q, want empty", got)
	}
}
