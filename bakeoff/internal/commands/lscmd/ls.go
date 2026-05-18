package lscmd

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"sync"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/apperror"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/commands"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/manifest"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/summary"
	"github.com/spf13/cobra"
)

type LsOptions struct {
	Out         string
	JSON        bool
	Facet       string
	TriageState string
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
			if err := commands.ValidateEnumFlag(opts.TriageState, "triage-state", "no", "dry_run", "yes", "stale"); err != nil {
				return err
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
	return cmd
}

func runLs(_ context.Context, f commands.Factory, opts *LsOptions) error {
	if _, err := os.Stat(opts.Out); err != nil {
		if opts.JSON {
			return summary.Print(f.Streams().Out, map[string]any{"schema_version": 1, "out_dir": opts.Out, "runs": []any{}})
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
		rows = append(rows, row)
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
		facet := stringValue(row["facet_id"])
		if facet == "" {
			facet = "-"
		}
		f.Streams().Printf("%s\t%s\t%s\t%s\ttriage:%s\t%s\n", stringValue(row["run_id"]), defaultString(row["type"], "?"), facet, defaultString(row["decision_kind"], "?"), defaultString(row["triage_state"], "no"), defaultString(row["finished_at"], "-"))
	}
	return nil
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

func stringValue(value any) string {
	text, _ := value.(string)
	return text
}

func defaultString(value any, fallback string) string {
	if text := stringValue(value); text != "" {
		return text
	}
	return fallback
}
