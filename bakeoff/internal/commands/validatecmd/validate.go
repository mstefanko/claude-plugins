package validatecmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/repocontext"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type ValidateOptions struct {
	WorkOrder string
}

type ContextOptions struct {
	WorkOrder    string
	Provider     string
	NoRepoLayout bool
}

func NewCmdValidate(f commands.Factory, runF func(context.Context, *ValidateOptions) error) *cobra.Command {
	opts := &ValidateOptions{}
	cmd := &cobra.Command{
		Use:           "validate WORK_ORDER",
		Short:         "validate and dry-run a work order",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.WorkOrder = args[0]
			if runF == nil {
				return runValidate(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.AddCommand(newCmdValidateContext(f, nil))
	return cmd
}

func newCmdValidateContext(f commands.Factory, runF func(context.Context, *ContextOptions) error) *cobra.Command {
	opts := &ContextOptions{}
	cmd := &cobra.Command{
		Use:           "context WORK_ORDER",
		Short:         "preview injected prompt context",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.WorkOrder = args[0]
			if runF == nil {
				return runValidateContext(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Provider, "provider", "", "preview one provider id")
	cmd.Flags().BoolVar(&opts.NoRepoLayout, "no-repo-layout", false, "suppress generated repo layout preview")
	return cmd
}

func runValidate(_ context.Context, f commands.Factory, opts *ValidateOptions) error {
	wo, err := workorder.Load(opts.WorkOrder)
	if err != nil {
		return commands.WrapValidation(err)
	}
	root, err := os.Getwd()
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	streams := f.Streams()
	if errors := validateErrors(root, wo); len(errors) > 0 {
		return commands.WrapValidation(&workorder.ValidationError{Message: strings.Join(errors, "\n")})
	}
	streams.Printf("valid work order\n")
	streams.Printf("  id:      %s\n", wo.ID)
	streams.Printf("  mode:    %s\n", wo.Type)
	streams.Printf("  run:     %s\n", wo.RunMode)
	if wo.Facet != nil {
		streams.Printf("  facet:   %s\n", wo.Facet.ID)
	}
	streams.Printf("  budgets: %s\n", workorder.FormatBudgetSummary(wo.Budgets))
	streams.Printf("  scope:   %s\n", wo.ScopePolicy.Enforcement)
	streams.Printf("  providers:\n")
	for _, provider := range wo.Providers {
		streams.Printf("    - %s: %s %s (%s, %s)\n", provider.ID, provider.Backend, provider.Model, provider.Scope, provider.Effort)
	}
	if wo.RunMode == workorder.RunModeSingleProvider {
		streams.Printf("  judge:   not run for single_provider\n")
	} else {
		streams.Printf("  judge:   %s %s (%s)\n", wo.Judge.Backend, wo.Judge.Model, wo.Judge.Effort)
	}
	for _, warning := range validateWarnings(root, wo) {
		streams.Printf("warning: %s\n", warning)
	}
	return nil
}

func runValidateContext(_ context.Context, f commands.Factory, opts *ContextOptions) error {
	wo, err := workorder.Load(opts.WorkOrder)
	if err != nil {
		return commands.WrapValidation(err)
	}
	root, err := os.Getwd()
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	providers, err := selectedProviders(wo, opts.Provider)
	if err != nil {
		return commands.WrapValidation(err)
	}
	streams := f.Streams()
	streams.Printf("context root: %s\n", root)
	for _, warning := range validateWarnings(root, wo) {
		streams.Printf("warning: %s\n", warning)
	}
	streams.Printf("\n<context>\n%s\n</context>\n", wo.Background)
	layoutBlock := ""
	if anySelectedReceivesLayout(wo, providers, opts.NoRepoLayout) {
		layoutBlock, err = repocontext.BuildLayoutBlock(root)
		if err != nil {
			return err
		}
		if layoutBlock != "" {
			streams.Printf("\n%s\n", layoutBlock)
		}
	}
	streams.Printf("\nproviders:\n")
	for _, provider := range providers {
		layoutEligible := repocontext.ParticipantReceivesLayout(wo.ScopePolicy, provider, opts.NoRepoLayout)
		if layoutEligible && layoutBlock != "" {
			streams.Printf("  - %s: receives <context>, <repo_layout> (scope: %s)\n", provider.ID, provider.Scope)
		} else if layoutEligible {
			streams.Printf("  - %s: receives <context>; <repo_layout> enabled but no entries were generated (scope: %s)\n", provider.ID, provider.Scope)
		} else {
			streams.Printf("  - %s: receives <context>; does not receive <repo_layout> (scope: %s)\n", provider.ID, provider.Scope)
		}
	}
	return nil
}

func selectedProviders(wo *workorder.WorkOrder, providerID string) ([]workorder.Participant, error) {
	if providerID == "" {
		return wo.Providers, nil
	}
	for _, provider := range wo.Providers {
		if provider.ID == providerID {
			return []workorder.Participant{provider}, nil
		}
	}
	return nil, workorder.Validationf("unknown provider id %q", providerID)
}

func anySelectedReceivesLayout(wo *workorder.WorkOrder, providers []workorder.Participant, disabled bool) bool {
	for _, provider := range providers {
		if repocontext.ParticipantReceivesLayout(wo.ScopePolicy, provider, disabled) {
			return true
		}
	}
	return false
}

func validateErrors(root string, wo *workorder.WorkOrder) []string {
	if wo == nil || wo.Build == nil {
		return nil
	}
	var errors []string
	for _, protectedPath := range wo.Build.ProtectedPaths {
		if _, err := os.Stat(filepath.Join(root, protectedPath)); err != nil {
			if os.IsNotExist(err) {
				errors = append(errors, `build.protected_paths references missing path "`+protectedPath+`" under <context-root>`)
			} else {
				errors = append(errors, `build.protected_paths references unreadable path "`+protectedPath+`": `+err.Error())
			}
		}
	}
	for _, verifier := range wo.Build.Verify {
		if verifier.Kind != "metric" {
			continue
		}
		if len(verifier.Argv) > 0 && repoRelativeCommand(verifier.Argv[0]) {
			commandPath := strings.TrimPrefix(verifier.Argv[0], "./")
			if _, err := os.Stat(filepath.Join(root, commandPath)); err != nil {
				if os.IsNotExist(err) {
					errors = append(errors, `metric verifier "`+verifier.ID+`" runs missing repo-relative command "`+verifier.Argv[0]+`" under <context-root>`)
				} else {
					errors = append(errors, `metric verifier "`+verifier.ID+`" cannot stat repo-relative command "`+verifier.Argv[0]+`": `+err.Error())
				}
			}
			if len(wo.Build.ProtectedPaths) == 0 {
				errors = append(errors, `metric verifier "`+verifier.ID+`" runs repo-relative command "`+verifier.Argv[0]+`" while build.protected_paths is empty; add the verifier script and any data fixtures to build.protected_paths`)
			}
		}
	}
	return errors
}

func validateWarnings(root string, wo *workorder.WorkOrder) []string {
	var warnings []string
	pathWarnings, err := repocontext.ValidateProsePaths(root, wo)
	if err == nil {
		for _, warning := range pathWarnings {
			message := fmt.Sprintf("%s references %q which does not exist under <context-root>", warning.Field, warning.Token)
			if len(warning.Suggestions) > 0 {
				message += "; did you mean one of: " + strings.Join(warning.Suggestions, ", ") + "?"
			}
			warnings = append(warnings, message)
		}
	}
	if warning := judgeFamilyWarning(wo); warning != "" {
		warnings = append(warnings, warning)
	}
	if warning := sameBackendModelScopeWarning(wo); warning != "" {
		warnings = append(warnings, warning)
	}
	if wo == nil || wo.Build == nil {
		return warnings
	}
	for _, verifier := range wo.Build.Verify {
		if verifier.Kind != "metric" {
			continue
		}
		if verifier.Metric != nil {
			_, hasNoiseFloor := verifier.Metric.Raw["noise_floor_percent"]
			if !hasNoiseFloor {
				warnings = append(warnings, `metric verifier "`+verifier.ID+`" omits metric.noise_floor_percent; declare a conservative noise floor so small differences do not look decisive`)
			}
			if hasNoiseFloor && verifier.Metric.MinRuns <= 1 {
				warnings = append(warnings, `metric verifier "`+verifier.ID+`" declares metric.noise_floor_percent but leaves metric.min_runs=1; use repeated runs so the noise floor reflects aggregate measurements`)
			}
		}
		if verifier.Metric != nil && verifier.Metric.MinRuns > 1 {
			warnings = append(warnings, `metric verifier "`+verifier.ID+`" sets metric.min_runs=`+strconv.Itoa(verifier.Metric.MinRuns)+`; final metric JSON must include "n" >= `+strconv.Itoa(verifier.Metric.MinRuns)+` or the metric comparison will be inconclusive`)
		}
	}
	return warnings
}

func sameBackendModelScopeWarning(wo *workorder.WorkOrder) string {
	if !workorder.SameBackendModelScopeRun(wo) {
		return ""
	}
	a := wo.Providers[0]
	b := wo.Providers[1]
	if a.Effort == b.Effort {
		return fmt.Sprintf("same-model duplicate advisory: providers %s and %s share backend, model, scope, and effort. This is an exact duplicate baseline: independent attempts, not independent model corroboration; no majority vote is possible with two workers.", a.ID, b.ID)
	}
	return fmt.Sprintf("same-model duplicate advisory: providers %s and %s share backend, model, and scope but use different effort. They are independent attempts with the same backend/model/scope, not exact duplicate sampling or independent model corroboration; no majority vote is possible with two workers.", a.ID, b.ID)
}

func judgeFamilyWarning(wo *workorder.WorkOrder) string {
	if wo == nil || wo.RunMode == workorder.RunModeSingleProvider || !judgeFamilyAdvisoryContext(wo) {
		return ""
	}
	providerBackends := make([]string, 0, len(wo.Providers))
	for _, participant := range wo.Providers {
		providerBackends = append(providerBackends, participant.Backend)
	}
	relation := provider.JudgeFamilyRelation(wo.Judge.Backend, providerBackends)
	switch relation {
	case provider.JudgeFamilyRelationSameAsAll:
		return judgeFamilyWarningText(wo.Judge.Backend, "all providers")
	case provider.JudgeFamilyRelationSameAsSome:
		matches := matchingProviderBackends(wo.Judge.Backend, wo.Providers)
		if len(matches) == 0 {
			return ""
		}
		target := "provider " + matches[0]
		if len(matches) > 1 {
			target = "providers " + strings.Join(matches, ", ")
		}
		return judgeFamilyWarningText(wo.Judge.Backend, target)
	default:
		return ""
	}
}

func judgeFamilyAdvisoryContext(wo *workorder.WorkOrder) bool {
	switch wo.Type {
	case "compare", "analyze", "build":
		return true
	case "gather":
		return wo.Facet != nil && wo.Facet.ID == "code-review"
	default:
		return false
	}
}

func matchingProviderBackends(judgeBackend string, providers []workorder.Participant) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, participant := range providers {
		if seen[participant.Backend] || !provider.SameBackendFamily(judgeBackend, participant.Backend) {
			continue
		}
		seen[participant.Backend] = true
		out = append(out, participant.Backend)
	}
	return out
}

func judgeFamilyWarningText(judgeBackend string, target string) string {
	return "judge family advisory: judge " + judgeBackend + " shares provider-family metadata with " + target + "; for high-stakes judge-heavy runs, run bakeoff doctor to check ready non-contestant judge backends. Advisory only; validation still succeeds."
}

func repoRelativeCommand(command string) bool {
	command = strings.TrimSpace(command)
	if command == "" || filepath.IsAbs(command) || strings.HasPrefix(command, "../") {
		return false
	}
	return strings.HasPrefix(command, "./") || strings.Contains(command, "/")
}
