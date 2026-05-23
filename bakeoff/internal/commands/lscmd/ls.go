package lscmd

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/jsonutil"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/ledger"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
	"github.com/spf13/cobra"
)

type LsOptions struct {
	Out         string
	JSON        bool
	Facet       string
	TriageState string
	Type        string
	SourceRun   string
	Limit       int
	LimitSet    bool
	History     bool
}

func NewCmdLs(f commands.Factory, runF func(context.Context, *LsOptions) error) *cobra.Command {
	_ = f
	opts := &LsOptions{Out: "runs"}
	cmd := &cobra.Command{
		Use:           "ls",
		Short:         "list past runs",
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          commands.ExactArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			opts.LimitSet = cmd.Flags().Changed("limit")
			if err := commands.ValidateEnumFlag(opts.TriageState, "triage-state", "no", "dry_run", "yes", "stale"); err != nil {
				return err
			}
			if err := commands.ValidateEnumFlag(opts.Type, "type", "gather", "compare", "analyze", "build", "escalation"); err != nil {
				return err
			}
			if opts.SourceRun != "" {
				if err := ledger.ValidateLookupRunID(opts.SourceRun); err != nil {
					return &apperror.ValidationError{Message: err.Error(), Err: err}
				}
			}
			if opts.LimitSet && opts.Limit < 0 {
				return &apperror.ValidationError{Message: "--limit must be greater than or equal to 0"}
			}
			if opts.JSON && opts.History {
				return &apperror.ValidationError{Message: "--history cannot be combined with --json"}
			}
			if runF == nil {
				return runLs(cmd.Context(), f, opts)
			}
			return runF(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.Out, "out", "runs", "run ledger directory (default: runs)")
	cmd.Flags().BoolVar(&opts.JSON, "json", false, "emit a manifest-backed JSON listing")
	cmd.Flags().StringVar(&opts.Facet, "facet", "", "filter by facet id")
	cmd.Flags().StringVar(&opts.TriageState, "triage-state", "", "filter by triage state")
	cmd.Flags().StringVar(&opts.Type, "type", "", "filter by run type")
	cmd.Flags().StringVar(&opts.SourceRun, "source-run", "", "filter escalation rows by source run id")
	cmd.Flags().IntVar(&opts.Limit, "limit", 0, "limit rows after filtering; 0 returns no rows")
	cmd.Flags().BoolVar(&opts.History, "history", false, "emit a compact recent-run history with work-order summaries")
	return cmd
}

func runLs(_ context.Context, f commands.Factory, opts *LsOptions) error {
	if _, err := os.Stat(opts.Out); err != nil {
		if opts.JSON {
			return summary.Print(f.Streams().Out, map[string]any{"schema_version": 1, "out_dir": opts.Out, "runs": []any{}})
		}
		if opts.History {
			f.Streams().Printf("No Bakeoff runs found under %s.\n", opts.Out)
			return nil
		}
		f.Streams().Printf("no runs found under %s\n", opts.Out)
		return nil
	}
	entries, err := os.ReadDir(opts.Out)
	if err != nil {
		return &apperror.RuntimeError{Err: err}
	}
	runDirs := []string{}
	for _, entry := range entries {
		if entry.IsDir() && entry.Name() != "latest" {
			runDirs = append(runDirs, filepath.Join(opts.Out, entry.Name()))
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(runDirs)))
	rows := []map[string]any{}
	for _, row := range rowsForLS(runDirs) {
		if opts.Facet != "" && row["facet_id"] != opts.Facet {
			continue
		}
		if opts.TriageState != "" && row["triage_state"] != opts.TriageState {
			continue
		}
		if opts.Type != "" && row["type"] != opts.Type {
			continue
		}
		if opts.SourceRun != "" && row["source_run_id"] != opts.SourceRun {
			continue
		}
		rows = append(rows, row)
	}
	sortRowsByFinishedAt(rows)
	totalRows := len(rows)
	if opts.History && !opts.LimitSet {
		opts.Limit = 10
		opts.LimitSet = true
	}
	if opts.LimitSet && opts.Limit < len(rows) {
		rows = rows[:opts.Limit]
	}
	if opts.History {
		printHistory(f, opts, rows, totalRows)
		return nil
	}
	if opts.JSON {
		outRows := make([]any, len(rows))
		for i, row := range rows {
			outRows[i] = row
		}
		if err := summary.Print(f.Streams().Out, map[string]any{"schema_version": 1, "out_dir": opts.Out, "runs": outRows}); err != nil {
			return &apperror.RuntimeError{Err: err}
		}
		return nil
	}
	f.Streams().Printf("run_id\ttype\tfacet\tdecision\ttriage\tfinished_at\n")
	for _, row := range rows {
		facet := jsonutil.StringValue(row["facet_id"])
		if facet == "" {
			facet = "-"
		}
		f.Streams().Printf("%s\t%s\t%s\t%s\ttriage:%s\t%s\n", jsonutil.StringValue(row["run_id"]), defaultString(row["type"], "?"), facet, defaultString(row["decision_kind"], "?"), defaultString(row["triage_state"], "no"), defaultString(row["finished_at"], "-"))
	}
	return nil
}

func sortRowsByFinishedAt(rows []map[string]any) {
	sort.SliceStable(rows, func(i, j int) bool {
		leftTime, leftOK := parseFinishedAt(jsonutil.StringValue(rows[i]["finished_at"]))
		rightTime, rightOK := parseFinishedAt(jsonutil.StringValue(rows[j]["finished_at"]))
		if leftOK != rightOK {
			return leftOK
		}
		if leftOK && !leftTime.Equal(rightTime) {
			return leftTime.After(rightTime)
		}
		return jsonutil.StringValue(rows[i]["run_id"]) < jsonutil.StringValue(rows[j]["run_id"])
	})
}

func parseFinishedAt(value string) (time.Time, bool) {
	if value == "" {
		return time.Time{}, false
	}
	parsed, err := time.Parse(time.RFC3339, value)
	return parsed, err == nil
}

func printHistory(f commands.Factory, opts *LsOptions, rows []map[string]any, totalRows int) {
	if totalRows == 0 {
		if opts.Facet != "" || opts.TriageState != "" || opts.Type != "" {
			f.Streams().Printf("No Bakeoff runs matched filters under %s.\n", opts.Out)
			return
		}
		f.Streams().Printf("No Bakeoff runs found under %s.\n", opts.Out)
		return
	}
	f.Streams().Printf("Recent Bakeoff runs (%d total, showing %d newest):\n\n", totalRows, len(rows))
	f.Streams().Printf("| finished | run id | type | facet | decision | triage | summary |\n")
	f.Streams().Printf("| --- | --- | --- | --- | --- | --- | --- |\n")
	for _, row := range rows {
		runDir := runDirForRow(opts.Out, row)
		f.Streams().Printf("| %s | %s | %s | %s | %s | %s | %s |\n",
			historyCell(displayFinishedAt(jsonutil.StringValue(row["finished_at"]))),
			historyCell(defaultString(row["run_id"], "-")),
			historyCell(defaultString(row["type"], "?")),
			historyCell(defaultString(row["facet_id"], "-")),
			historyCell(defaultString(row["decision_kind"], "?")),
			historyCell(defaultString(row["triage_state"], "no")),
			historyCell(workOrderSummary(runDir)),
		)
	}
	f.Streams().Printf("\nOpen one with `/bakeoff:inspect <run-id>`.\n")
}

func displayFinishedAt(value string) string {
	if parsed, ok := parseFinishedAt(value); ok {
		return parsed.Format("2006-01-02 15:04")
	}
	if value != "" {
		return value
	}
	return "-"
}

func historyCell(value string) string {
	if strings.TrimSpace(value) == "" {
		value = "-"
	}
	return strings.ReplaceAll(value, "|", `\|`)
}

func runDirForRow(outDir string, row map[string]any) string {
	if manifestPath := jsonutil.StringValue(row["manifest_path"]); manifestPath != "" {
		return filepath.Dir(manifestPath)
	}
	if reportPath := jsonutil.StringValue(row["report_path"]); reportPath != "" {
		return filepath.Dir(reportPath)
	}
	return filepath.Join(outDir, jsonutil.StringValue(row["run_id"]))
}

func workOrderSummary(runDir string) string {
	value, err := workorder.ReadOptionalJSON(filepath.Join(runDir, "work-order.json"))
	if err != nil {
		return "-"
	}
	obj, _ := value.(map[string]any)
	if obj == nil {
		return "-"
	}
	if summary := firstSummaryValue(obj["goal"]); summary != "" {
		return truncateSummary(summary)
	}
	if summary := firstSummaryValue(obj["background"]); summary != "" {
		return truncateSummary(summary)
	}
	return "-"
}

func firstSummaryValue(value any) string {
	if text, ok := value.(string); ok {
		return collapseSummary(text)
	}
	items, ok := value.([]any)
	if !ok {
		return ""
	}
	for _, item := range items {
		if text, ok := item.(string); ok {
			if collapsed := collapseSummary(text); collapsed != "" {
				return collapsed
			}
		}
	}
	return ""
}

func collapseSummary(value string) string {
	return strings.Join(strings.Fields(value), " ")
}

func truncateSummary(value string) string {
	const maxRunes = 100
	runes := []rune(value)
	if len(runes) <= maxRunes {
		return value
	}
	return string(runes[:maxRunes-3]) + "..."
}

func rowsForLS(runDirs []string) []map[string]any {
	rows := make([]map[string]any, len(runDirs))
	workers := runtime.GOMAXPROCS(0)
	if workers > 16 {
		workers = 16
	}
	if workers < 2 || len(runDirs) < 2 {
		for i, runDir := range runDirs {
			rows[i] = manifest.RowForLS(runDir)
		}
		return rows
	}

	jobs := make(chan int)
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range jobs {
				rows[index] = manifest.RowForLS(runDirs[index])
			}
		}()
	}
	for i := range runDirs {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	return rows
}

func defaultString(value any, fallback string) string {
	if text := jsonutil.StringValue(value); text != "" {
		return text
	}
	return fallback
}
