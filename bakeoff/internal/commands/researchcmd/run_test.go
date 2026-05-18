package researchcmd

import (
	"bytes"
	"context"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/buildinfo"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/output"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/provider"
	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

type researchTestFactory struct {
	streams output.Streams
}

func (f researchTestFactory) Streams() output.Streams {
	return f.streams
}

func (f researchTestFactory) BuildInfo() buildinfo.Info {
	return buildinfo.Current()
}

func (f researchTestFactory) Now() time.Time {
	return time.Unix(0, 0).UTC()
}

func (f researchTestFactory) LookupProvider(name string) (string, error) {
	return exec.LookPath(name)
}

func (f researchTestFactory) Capabilities() *provider.CapabilityRegistry {
	return provider.NewCapabilityRegistry(f.LookupProvider)
}

func TestCopyReplayContextArtifactsRequiresCompleteSet(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source")
	target := filepath.Join(root, "target")
	if err := os.MkdirAll(source, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(target, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "review-context.md"), []byte("context\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	err := copyReplayContextArtifacts(source, target)
	if err == nil || !strings.Contains(err.Error(), "partial review-context artifact set") {
		t.Fatalf("expected partial replay context error, got %v", err)
	}
}

func TestForceReviewContextCaptureFailurePreservesExistingRun(t *testing.T) {
	root := t.TempDir()
	outDir := filepath.Join(root, "runs")
	runDir := filepath.Join(outDir, "existing-run")
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(runDir, "sentinel.txt")
	if err := os.WriteFile(sentinel, []byte("keep me\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "capture-failure",
		"type":           "gather",
		"goal":           "test",
		"background":     "",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "m", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "m", "scope": "codebase"},
		},
		"judge":   map[string]any{"backend": "claude", "model": "judge"},
		"budgets": map[string]any{"wall_clock_seconds": 1, "max_output_bytes": 1000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	err := RunResearch(context.Background(), nil, &ResearchOptions{
		WorkOrder: workOrderPath,
		Out:       outDir,
		RunID:     "existing-run",
		Force:     true,
		Base:      "definitely-missing-review-base-ref",
		NoTriage:  true,
	})
	if err == nil || !strings.Contains(err.Error(), "review context base ref not found") {
		t.Fatalf("expected review-context capture error, got %v", err)
	}
	data, readErr := os.ReadFile(sentinel)
	if readErr != nil {
		t.Fatalf("existing run was removed: %v", readErr)
	}
	if string(data) != "keep me\n" {
		t.Fatalf("existing run sentinel changed: %q", string(data))
	}
}

func TestRunResearchScrubsSecretsFromProviderArtifacts(t *testing.T) {
	root := t.TempDir()
	fakeBin := filepath.Join(root, "bin")
	if err := os.MkdirAll(fakeBin, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExecutable(t, filepath.Join(fakeBin, "claude"), `#!/bin/sh
case " $* " in
  *" --help "*) printf '%s\n' '--allowedTools --disallowedTools'; exit 0 ;;
esac
printf 'provider-env:%s:%s:%s\n' "$ANTHROPIC_API_KEY" "$OPENAI_API_KEY" "$APP_JWT"
cat >/dev/null
cat <<'JSON'
<final_json>{"status":"complete","claims":[{"id":"C-001","claim":"Provider did not receive scrubbed secrets.","evidence":["fake:1"],"confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>
JSON
`)
	writeExecutable(t, filepath.Join(fakeBin, "codex"), `#!/bin/sh
case " $* " in
  *" --help "*) printf '%s\n' '--sandbox read-only workspace-write --disable --output-last-message'; exit 0 ;;
esac
printf 'provider-env:%s:%s:%s\n' "$ANTHROPIC_API_KEY" "$OPENAI_API_KEY" "$APP_JWT"
cat >/dev/null
exit 2
`)
	t.Setenv("PATH", fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	secrets := []string{"anthropic-secret-smoke", "openai-secret-smoke", "jwt-secret-smoke"}
	t.Setenv("ANTHROPIC_API_KEY", secrets[0])
	t.Setenv("OPENAI_API_KEY", secrets[1])
	t.Setenv("APP_JWT", secrets[2])

	workOrderPath := filepath.Join(root, "work-order.json")
	if err := workorder.WriteJSONAtomic(workOrderPath, map[string]any{
		"schema_version": 1,
		"id":             "secret-smoke",
		"type":           "gather",
		"goal":           "Gather a fact.",
		"background":     "Secret leak smoke test.",
		"providers": []map[string]any{
			{"id": "claude", "backend": "claude", "model": "claude-test", "scope": "codebase"},
			{"id": "codex", "backend": "codex", "model": "codex-test", "scope": "web"},
		},
		"scope_policy": map[string]any{"enforcement": "best_effort"},
		"judge":        map[string]any{"backend": "claude", "model": "judge-test"},
		"budgets":      map[string]any{"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
	}); err != nil {
		t.Fatal(err)
	}

	var out, errOut bytes.Buffer
	outDir := filepath.Join(root, "runs")
	factory := researchTestFactory{streams: output.NewStreams(&out, &errOut)}
	err := RunResearch(context.Background(), factory, &ResearchOptions{WorkOrder: workOrderPath, Out: outDir, RunID: "secret-smoke", Quiet: true, NoTriage: true})
	if err != nil {
		t.Fatalf("RunResearch returned error: %v\nstdout:\n%s\nstderr:\n%s", err, out.String(), errOut.String())
	}
	runDir := filepath.Join(outDir, "secret-smoke")
	err = filepath.WalkDir(runDir, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		for _, secret := range secrets {
			if bytes.Contains(data, []byte(secret)) {
				t.Fatalf("secret %q leaked into %s", secret, path)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestResearchResultLineSummarizesGatherAndWinnerModes(t *testing.T) {
	gather := researchResultLine(&workorder.WorkOrder{Type: "gather"}, map[string]any{
		"mode":          "gather",
		"decision_kind": "structured_union",
		"judge_ran":     true,
	}, "")
	if gather != "structured_union, judge=yes" {
		t.Fatalf("gather result line = %q", gather)
	}
	compare := researchResultLine(&workorder.WorkOrder{Type: "compare"}, map[string]any{
		"decision_kind":    "pick_winner",
		"canonical_winner": "claude",
		"spine_tiebreak":   "most_corroborated",
	}, "")
	if compare != "winner=claude, basis=most_corroborated" {
		t.Fatalf("compare result line = %q", compare)
	}
}

func writeExecutable(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o755); err != nil {
		t.Fatal(err)
	}
}
