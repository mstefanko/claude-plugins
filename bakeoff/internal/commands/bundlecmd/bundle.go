package bundlecmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/runlinks"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/triage"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type BundleOptions struct {
	RunID string
	Out   string
	Write bool
}

func NewCmdBundle(f commands.Factory, runF func(context.Context, *BundleOptions) error) *cobra.Command {
	_ = f
	opts := &BundleOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "bundle RUN_ID",
		Short:         "print a source run with related escalations",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.RunID = args[0]
			if runF == nil {
				return runBundle(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.Write, "write", false, "write derived related-report.md under the source run")
	return cmd
}

func runBundle(_ context.Context, f commands.Factory, opts *BundleOptions) error {
	if err := ledger.ValidateLookupRunID(opts.RunID); err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	selectedDir, err := ledger.ResolveRunDir(opts.Out, opts.RunID)
	if err != nil {
		return &apperror.ValidationError{Message: err.Error(), Err: err}
	}
	sourceID, sourceDir, err := resolveBundleSource(opts.Out, opts.RunID, selectedDir)
	if err != nil {
		return err
	}
	text := renderBundle(opts.Out, sourceID, sourceDir)
	if opts.Write {
		path := filepath.Join(sourceDir, "related-report.md")
		if err := workorder.WriteTextAtomic(path, text); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		f.Streams().Printf("%s\nwrote: %s\n", text, path)
		return nil
	}
	f.Streams().Printf("%s", text)
	return nil
}

func resolveBundleSource(outDir string, selectedRunID string, selectedDir string) (string, string, error) {
	selectedID := selectedRunID
	if selectedID == "" || selectedID == "latest" || ledger.IsPathLikeRunID(selectedID) {
		selectedID = filepath.Base(selectedDir)
	}
	manifest, _ := runlinks.RunManifest(selectedDir)
	if jsonutil.StringValue(manifest["type"]) != "escalation" {
		return selectedID, selectedDir, nil
	}
	sourceID := jsonutil.StringValue(manifest["source_run_id"])
	if sourceID == "" {
		return "", "", &apperror.ValidationError{Message: selectedDir + " is an escalation without source_run_id"}
	}
	sourceDir, err := ledger.ResolveRunDir(outDir, sourceID)
	if err == nil {
		return sourceID, sourceDir, nil
	}
	if sourceDir = jsonutil.StringValue(manifest["source_run_dir"]); sourceDir != "" {
		if info, statErr := os.Stat(sourceDir); statErr == nil && info.IsDir() {
			return sourceID, sourceDir, nil
		}
	}
	return "", "", &apperror.ValidationError{Message: "source run not found: " + sourceID, Err: err}
}

func renderBundle(outDir string, sourceID string, sourceDir string) string {
	sourceManifest, _ := runlinks.RunManifest(sourceDir)
	sourceDecision := readObject(filepath.Join(sourceDir, "decision.json"))
	sourceReport := filepath.Join(sourceDir, "report.md")
	steps := newStepCollector()
	lines := []string{
		"# Bakeoff Related Run Bundle: " + sourceID,
		"",
		"## Source Run",
		"",
		"- Run: `" + sourceID + "`",
		"- Directory: `" + sourceDir + "`",
		"- Type: `" + defaultText(jsonutil.StringValue(sourceManifest["type"]), "?") + "`",
		"- Decision: `" + defaultText(jsonutil.StringValue(sourceDecision["decision_kind"]), "?") + "`",
		"- Report: `" + sourceReport + "`",
		"- Triage: " + triageLine(sourceID, outDir, sourceDir, steps),
		"",
	}
	children := runlinks.EscalationsForSource(ledger.OutputDirForResolvedRun(outDir, sourceDir), sourceID)
	lines = append(lines, "## Child Escalations", "")
	if len(children) == 0 {
		lines = append(lines, "- None found.", "")
	} else {
		lines = append(lines,
			"| Run | Mode | Provider | Decision | Triage | Report |",
			"| --- | --- | --- | --- | --- | --- |",
		)
		for _, child := range children {
			lines = append(lines, fmt.Sprintf("| `%s` | `%s` | `%s` | `%s` | %s | `%s` |",
				child.RunID,
				defaultText(child.Mode, "-"),
				defaultText(child.AddedProvider, "-"),
				defaultText(child.DecisionKind, "-"),
				triageTableCell(child.RunID, outDir, child.RunDir, steps),
				child.ReportPath,
			))
		}
		lines = append(lines, "")
		lines = append(lines, "## Escalation Details", "")
		for _, child := range children {
			lines = append(lines,
				"### "+child.RunID,
				"",
				"- Mode: `"+defaultText(child.Mode, "-")+"`",
				"- Added provider: `"+defaultText(child.AddedProvider, "-")+"`",
				"- Decision: `"+defaultText(child.DecisionKind, "-")+"`",
				"- Report: `"+child.ReportPath+"`",
				"- Triage: "+triageLine(child.RunID, outDir, child.RunDir, steps),
				"",
			)
		}
	}
	lines = append(lines, "## Operator Next Steps", "")
	for _, step := range steps.items {
		lines = append(lines, "- "+step)
	}
	if len(steps.items) == 0 {
		lines = append(lines, "- No immediate triage follow-up detected.")
	}
	lines = append(lines, "- Write this derived report if needed: `"+bundleWriteCommand(sourceID, outDir)+"`")
	lines = append(lines, "")
	return strings.Join(lines, "\n")
}

type stepCollector struct {
	seen  map[string]bool
	items []string
}

func newStepCollector() *stepCollector {
	return &stepCollector{seen: map[string]bool{}}
}

func (s *stepCollector) add(step string) {
	if step == "" || s.seen[step] {
		return
	}
	s.seen[step] = true
	s.items = append(s.items, step)
}

func triageTableCell(runID string, outDir string, runDir string, steps *stepCollector) string {
	return strings.ReplaceAll(triageLine(runID, outDir, runDir, steps), "|", `\|`)
}

func triageLine(runID string, outDir string, runDir string, steps *stepCollector) string {
	state, staleInputs := triage.DisplayStateDetail(runDir)
	switch state {
	case "yes":
		if triage.ZeroSelected(runDir) {
			steps.add("inspect zero-selected triage for `" + runID + "`: " + triage.ZeroSelectedMessage)
			return "`yes` (" + triage.ZeroSelectedMessage + ")"
		}
		return "`yes`"
	case "stale":
		steps.add("rerun stale triage for `" + runID + "`: `" + ledger.BakeoffTriageCommand(runID, outDir, true) + "`")
		return "`stale`" + triage.StaleInputsText(staleInputs)
	case "dry_run":
		steps.add("finish dry-run triage for `" + runID + "`: `" + ledger.BakeoffTriageCommand(runID, outDir, true) + "`")
		return "`dry_run`"
	case "failed":
		status := triage.AttemptStatus(runDir)
		if status == "" {
			status = "failed"
		}
		steps.add("retry failed triage for `" + runID + "`: `" + ledger.BakeoffTriageCommand(runID, outDir, true) + "`")
		return "`failed` (" + status + ")"
	default:
		if recommendation := triageRecommendation(runDir); recommendation != "" {
			steps.add("run missing triage for `" + runID + "`: `" + ledger.BakeoffTriageCommand(runID, outDir, false) + "` (" + recommendation + ")")
		}
		return "`no`"
	}
}

func triageRecommendation(runDir string) string {
	wo, err := workorder.Load(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		return ""
	}
	decision := readObject(filepath.Join(runDir, "decision.json"))
	reportData, err := os.ReadFile(filepath.Join(runDir, "report.md"))
	if err != nil {
		return ""
	}
	return triage.ShouldRecommendTriage(wo.Raw, decision, string(reportData))
}

func readObject(path string) map[string]any {
	value, err := workorder.ReadOptionalJSON(path)
	if err != nil {
		return map[string]any{}
	}
	obj, _ := value.(map[string]any)
	if obj == nil {
		return map[string]any{}
	}
	return obj
}

func defaultText(value string, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func bundleWriteCommand(runID string, outDir string) string {
	cmd := "bakeoff bundle " + runID
	if outDir != "runs" {
		cmd += " --out " + outDir
	}
	return cmd + " --write"
}
