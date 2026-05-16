package commands

import (
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/spf13/cobra"
)

func ExactArgs(count int) cobra.PositionalArgs {
	return func(cmd *cobra.Command, args []string) error {
		if len(args) != count {
			return apperror.Usagef("%s accepts %d arg(s), received %d", cmd.CommandPath(), count, len(args))
		}
		return nil
	}
}

func OneOf(label string, values ...string) func(string) error {
	allowed := map[string]struct{}{}
	for _, value := range values {
		allowed[value] = struct{}{}
	}
	return func(value string) error {
		if _, ok := allowed[value]; ok {
			return nil
		}
		return apperror.Validationf("%s must be one of: %s (got %q)", label, strings.Join(values, ", "), value)
	}
}

func ValidateEnumFlag(value string, label string, values ...string) error {
	if value == "" {
		return nil
	}
	if err := OneOf(label, values...)(value); err != nil {
		return err
	}
	return nil
}
