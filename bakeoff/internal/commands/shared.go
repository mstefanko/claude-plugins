package commands

import (
	"errors"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type Factory interface {
	Streams() output.Streams
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
