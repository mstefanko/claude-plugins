package commands

import (
	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
)

type Factory interface {
	Streams() output.Streams
}

func PlaceholderError(command string) error {
	return apperror.Runtimef("%s command is not implemented in bakeoff-go yet", command)
}
