package runner

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/mstefanko/claude-plugins/bakeoff/internal/workorder"
)

func TestExtractFinalJSONUsesLastBlockAndIgnoresTagsInStrings(t *testing.T) {
	payload, err := ExtractFinalJSON(`<final_json>{"first": true}</final_json>
noise
<final_json>{"second": true, "claim": "literal <final_json>{}</final_json> text"}</final_json>`, "stdout")
	if err != nil {
		t.Fatal(err)
	}
	obj := payload.(map[string]any)
	if obj["second"] != true {
		t.Fatalf("got %#v", obj)
	}
	if obj["claim"] != "literal <final_json>{}</final_json> text" {
		t.Fatalf("tag-like string changed: %#v", obj["claim"])
	}
}

func TestExtractFinalJSONReportsSourceLabel(t *testing.T) {
	_, err := ExtractFinalJSON("plain prose", "last-message artifact")
	if err == nil || err.Error() != "last-message artifact is missing a <final_json>...</final_json> block" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestRunProviderReportsSchemaErrorForMissingFinalJSON(t *testing.T) {
	result := RunProvider(context.Background(), helperOptions("plain", Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000}))
	if result.Status != StatusSchemaError {
		t.Fatalf("status = %s", result.Status)
	}
}

func TestRunProviderPrefersNonemptyLastMessage(t *testing.T) {
	lastMessage := filepath.Join(t.TempDir(), "last-message.txt")
	opts := helperOptionsWithArgs(Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000}, "last-message", lastMessage)
	opts.FinalMessagePath = lastMessage
	result := RunProvider(context.Background(), opts)
	if result.Status != StatusOK {
		t.Fatalf("status = %s stderr=%q", result.Status, result.Stderr)
	}
	if result.FinalJSONSource != FinalJSONSourceLastMessage {
		t.Fatalf("source = %s", result.FinalJSONSource)
	}
	if !reflect.DeepEqual(result.FinalJSON, map[string]any{"ok": true}) {
		t.Fatalf("final_json = %#v", result.FinalJSON)
	}
}

func TestRunProviderFallsBackToStdoutWhenLastMessageIsEmpty(t *testing.T) {
	lastMessage := filepath.Join(t.TempDir(), "last-message.txt")
	opts := helperOptionsWithArgs(Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000}, "empty-last-message", lastMessage)
	opts.FinalMessagePath = lastMessage
	result := RunProvider(context.Background(), opts)
	if result.Status != StatusOK {
		t.Fatalf("status = %s stderr=%q", result.Status, result.Stderr)
	}
	if result.FinalJSONSource != FinalJSONSourceStdout {
		t.Fatalf("source = %s", result.FinalJSONSource)
	}
}

func TestRunProviderFormatRetryRecoversZeroExitSchemaError(t *testing.T) {
	result := RunProviderWithFormatRetry(context.Background(), Options{
		Argv:    helperArgv("retry"),
		Env:     helperEnv(),
		Prompt:  "Return ok=true.",
		Budgets: Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000},
		Validator: func(data any) (any, error) {
			obj := data.(map[string]any)
			if obj["ok"] != true {
				return nil, fmt.Errorf("ok must be true")
			}
			return data, nil
		},
	})
	if result.Status != StatusOKAfterFormatRetry {
		t.Fatalf("status = %s stderr=%q", result.Status, result.Stderr)
	}
	if result.FormatRetry == nil || result.FormatRetry.InitialStatus.Status != StatusSchemaError || result.FormatRetry.RetryStatus.Status != StatusOK {
		t.Fatalf("format retry summary = %#v", result.FormatRetry)
	}
	if result.RepairArtifacts == nil || !strings.Contains(result.RepairArtifacts.Prompt, FormatRetryMarker) {
		t.Fatalf("repair artifacts missing retry marker: %#v", result.RepairArtifacts)
	}
}

func TestRunProviderReportsOutputCapAndSalvage(t *testing.T) {
	capped := RunProvider(context.Background(), helperOptions("output-cap", Budgets{WallClockSeconds: 3, MaxOutputBytes: 100}))
	if capped.Status != StatusOutputCap {
		t.Fatalf("status = %s", capped.Status)
	}
	if !strings.Contains(capped.Stdout, "[TRUNCATED at 100 bytes]") || !capped.StdoutTruncated {
		t.Fatalf("stdout was not marked truncated: %#v", capped)
	}
	if capped.StdoutBytes > 100 || capped.StdoutObservedBytes <= capped.StdoutBytes {
		t.Fatalf("unexpected byte counts: %#v", capped)
	}

	salvaged := RunProvider(context.Background(), helperOptions("salvage", Budgets{
		WallClockSeconds:      3,
		MaxOutputBytes:        120,
		MaxOutputOverrunBytes: 500,
		OutputCapGraceSeconds: 5,
	}))
	if salvaged.Status != StatusOK {
		t.Fatalf("salvage status = %s stderr=%q stdout=%q", salvaged.Status, salvaged.Stderr, salvaged.Stdout)
	}
	if !salvaged.StdoutTruncated || salvaged.StdoutObservedBytes <= salvaged.StdoutBytes {
		t.Fatalf("salvage truncation metadata missing: %#v", salvaged)
	}
}

func TestRunProviderHardStopsOnOutputCapGraceAndOverrun(t *testing.T) {
	grace := RunProvider(context.Background(), helperOptions("ignore-term-output", Budgets{
		WallClockSeconds:      10,
		MaxOutputBytes:        100,
		MaxOutputOverrunBytes: 10000,
		OutputCapGraceSeconds: 0,
	}))
	if grace.Status != StatusOutputCap {
		t.Fatalf("status = %s", grace.Status)
	}
	if grace.OutputCap == nil || (grace.OutputCap.Reason != OutputCapCaptureLimit && grace.OutputCap.Reason != OutputCapGraceTimeout) {
		t.Fatalf("output cap metadata = %#v", grace.OutputCap)
	}
	if grace.WallSeconds >= 3 {
		t.Fatalf("hard stop was too slow: %.3fs", grace.WallSeconds)
	}

	overrun := RunProvider(context.Background(), helperOptions("overrun", Budgets{
		WallClockSeconds:      10,
		MaxOutputBytes:        100,
		MaxOutputOverrunBytes: 1,
		OutputCapGraceSeconds: 30,
	}))
	if overrun.Status != StatusOutputCap || overrun.OutputCap == nil || overrun.OutputCap.Reason != OutputCapOverrunLimit {
		t.Fatalf("overrun result = %#v", overrun)
	}

	zeroOverrun := RunProvider(context.Background(), helperOptions("overrun", Budgets{
		WallClockSeconds:           10,
		MaxOutputBytes:             100,
		MaxOutputOverrunBytes:      0,
		MaxOutputOverrunBytesIsSet: true,
		OutputCapGraceSeconds:      30,
	}))
	if zeroOverrun.Status != StatusOutputCap || zeroOverrun.OutputCap == nil || zeroOverrun.OutputCap.Reason != OutputCapOverrunLimit {
		t.Fatalf("zero overrun result = %#v", zeroOverrun)
	}
	if zeroOverrun.OutputCap.MaxOutputOverrunBytes != 0 {
		t.Fatalf("zero overrun budget was not preserved: %#v", zeroOverrun.OutputCap)
	}
}

func TestRunProviderReportsStderrTruncationWithoutFailingSuccess(t *testing.T) {
	result := RunProvider(context.Background(), helperOptions("stderr-trunc", Budgets{WallClockSeconds: 3, MaxOutputBytes: 100}))
	if result.Status != StatusOK {
		t.Fatalf("status = %s stderr=%q", result.Status, result.Stderr)
	}
	if !result.StderrTruncated || !strings.Contains(result.Stderr, "[STDERR TRUNCATED at 100 bytes]") {
		t.Fatalf("stderr truncation missing: %#v", result)
	}
	if result.StderrBytes > 100 {
		t.Fatalf("stderr_bytes = %d", result.StderrBytes)
	}

	headTail := RunProvider(context.Background(), helperOptions("stderr-head-tail", Budgets{WallClockSeconds: 3, MaxOutputBytes: 100}))
	if headTail.Status != StatusOK {
		t.Fatalf("head/tail status = %s stderr=%q", headTail.Status, headTail.Stderr)
	}
	for _, want := range []string{"stderr-head-", "[STDERR TAIL]", "-stderr-tail"} {
		if !strings.Contains(headTail.Stderr, want) {
			t.Fatalf("stderr head/tail output missing %q: %q", want, headTail.Stderr)
		}
	}
	if headTail.StderrBytes > 100 || headTail.StderrObservedBytes <= headTail.StderrBytes {
		t.Fatalf("unexpected head/tail byte counts: %#v", headTail)
	}
}

func TestRunProviderReportsClosedStdinDiagnostic(t *testing.T) {
	result := RunProvider(context.Background(), Options{
		Argv:    helperArgv("close-stdin"),
		Env:     helperEnv(),
		Prompt:  strings.Repeat("x", 1_000_000),
		Budgets: Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000},
	})
	if result.Status != StatusExitError {
		t.Fatalf("status = %s", result.Status)
	}
	if !strings.Contains(result.Stderr, "provider closed stdin before reading prompt") {
		t.Fatalf("missing stdin diagnostic: %q", result.Stderr)
	}
}

func TestRunProviderHeartbeatTicksForQuietProcess(t *testing.T) {
	var ticks []Tick
	result := RunProvider(context.Background(), Options{
		Argv:    helperArgv("quiet"),
		Env:     helperEnv(),
		Budgets: Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000, HeartbeatSeconds: 1},
		OnTick: func(tick Tick) {
			ticks = append(ticks, tick)
		},
	})
	if result.Status != StatusTimeout {
		t.Fatalf("status = %s", result.Status)
	}
	if len(ticks) < 2 {
		t.Fatalf("expected heartbeat ticks, got %#v", ticks)
	}
	for i := 1; i < len(ticks); i++ {
		if ticks[i].Elapsed < ticks[i-1].Elapsed {
			t.Fatalf("ticks not sorted: %#v", ticks)
		}
	}
	if result.IO.HeartbeatCount != len(ticks) {
		t.Fatalf("heartbeat count = %d ticks=%d", result.IO.HeartbeatCount, len(ticks))
	}
}

func TestRunProviderReportsCancelledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()
	result := RunProvider(ctx, helperOptions("quiet", Budgets{WallClockSeconds: 5, MaxOutputBytes: 2000}))
	if result.Status != StatusCancelled {
		t.Fatalf("status = %s stderr=%q", result.Status, result.Stderr)
	}
}

func TestRunProviderPrefersOutputCapWhenTimeoutAlsoFires(t *testing.T) {
	result := RunProvider(context.Background(), helperOptions("ignore-term-output", Budgets{
		WallClockSeconds:      1,
		MaxOutputBytes:        100,
		MaxOutputOverrunBytes: 10000,
		OutputCapGraceSeconds: 5,
	}))
	if result.Status != StatusOutputCap {
		t.Fatalf("status = %s output_cap=%#v", result.Status, result.OutputCap)
	}
	if result.OutputCap == nil {
		t.Fatalf("missing output cap metadata: %#v", result)
	}
}

func TestRunProviderKillsProcessGroup(t *testing.T) {
	pidfile := filepath.Join(t.TempDir(), "child.pid")
	result := RunProvider(context.Background(), helperOptionsWithArgs(Budgets{WallClockSeconds: 1, MaxOutputBytes: 2000}, "spawn-child", pidfile))
	if result.Status != StatusTimeout {
		t.Fatalf("status = %s stderr=%q", result.Status, result.Stderr)
	}
	data, err := os.ReadFile(pidfile)
	if err != nil {
		t.Fatal(err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if !processAlive(pid) {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("child process %d still alive after process-group cleanup", pid)
}

func TestRunProviderParityFakeScriptScenarios(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 is not available for parity fake-provider script test")
	}
	script := filepath.Join(repoRoot(t), "tests", "parity", "fakes", "fake_provider.py")
	baseEnv := append(os.Environ(), "BAKEOFF_FAKE_PROVIDER_NAME=claude")

	outputCap := RunProvider(context.Background(), Options{
		Argv:    []string{python, script},
		Env:     append(baseEnv, "BAKEOFF_FAKE_OUTPUT_CAP_PROVIDERS=claude"),
		Budgets: Budgets{WallClockSeconds: 3, MaxOutputBytes: 120, OutputCapGraceSeconds: 1, MaxOutputOverrunBytes: 500},
	})
	if outputCap.Status != StatusOutputCap {
		t.Fatalf("fake output cap status = %s", outputCap.Status)
	}

	salvage := RunProvider(context.Background(), Options{
		Argv:    []string{python, script},
		Env:     append(baseEnv, "BAKEOFF_FAKE_OUTPUT_CAP_SALVAGE_PROVIDERS=claude"),
		Budgets: Budgets{WallClockSeconds: 3, MaxOutputBytes: 400, OutputCapGraceSeconds: 5, MaxOutputOverrunBytes: 1000},
		Validator: func(data any) (any, error) {
			return workorder.ValidateWorkerResult(data, "gather")
		},
	})
	if salvage.Status != StatusOK {
		t.Fatalf("fake salvage result = %#v", salvage)
	}

	retry := RunProviderWithFormatRetry(context.Background(), Options{
		Argv:    []string{python, script},
		Env:     append(baseEnv, "BAKEOFF_FAKE_REPAIR_PROVIDERS=claude"),
		Prompt:  "worker prompt",
		Budgets: Budgets{WallClockSeconds: 3, MaxOutputBytes: 2000},
		Validator: func(data any) (any, error) {
			return workorder.ValidateWorkerResult(data, "gather")
		},
	})
	if retry.Status != StatusOKAfterFormatRetry {
		t.Fatalf("fake retry status = %s stderr=%q", retry.Status, retry.Stderr)
	}
}

func helperOptions(mode string, budgets Budgets) Options {
	return helperOptionsWithArgs(budgets, mode)
}

func helperOptionsWithArgs(budgets Budgets, args ...string) Options {
	return Options{Argv: helperArgv(args...), Env: helperEnv(), Budgets: budgets}
}

func repoRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}

func helperArgv(args ...string) []string {
	argv := []string{os.Args[0], "-test.run=TestHelperProcess", "--"}
	return append(argv, args...)
}

func helperEnv() []string {
	return append(os.Environ(), "BAKEOFF_RUNNER_HELPER=1")
}

func processAlive(pid int) bool {
	err := syscall.Kill(pid, 0)
	return err == nil
}

func TestHelperProcess(t *testing.T) {
	if os.Getenv("BAKEOFF_RUNNER_HELPER") != "1" {
		return
	}
	args := os.Args
	for len(args) > 0 && args[0] != "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		os.Exit(2)
	}
	args = args[1:]
	if len(args) == 0 {
		os.Exit(2)
	}
	switch args[0] {
	case "plain":
		fmt.Print("plain prose")
	case "final":
		fmt.Print(`<final_json>{"ok": true}</final_json>`)
	case "last-message":
		if err := os.WriteFile(args[1], []byte(`<final_json>{"ok": true}</final_json>`), 0o644); err != nil {
			panic(err)
		}
		fmt.Print("plain prose without final json")
	case "empty-last-message":
		if err := os.WriteFile(args[1], nil, 0o644); err != nil {
			panic(err)
		}
		fmt.Print(`<final_json>{"ok": true}</final_json>`)
	case "retry":
		prompt, _ := io.ReadAll(os.Stdin)
		if strings.Contains(string(prompt), FormatRetryMarker) {
			fmt.Print(`<final_json>{"ok": true}</final_json>`)
		} else {
			fmt.Print(`<final_json>{"ok": false}</final_json>`)
		}
	case "output-cap":
		fmt.Print(strings.Repeat("x", 5000))
	case "salvage":
		fmt.Print(strings.Repeat("x", 200))
		fmt.Print(`<final_json>{"ok": true}</final_json>`)
	case "ignore-term-output":
		signalIgnoreTerm()
		fmt.Print(strings.Repeat("x", 5000))
		time.Sleep(5 * time.Second)
	case "overrun":
		fmt.Print(strings.Repeat("x", 5000))
		time.Sleep(5 * time.Second)
	case "stderr-trunc":
		fmt.Fprint(os.Stderr, strings.Repeat("e", 5000))
		fmt.Print(`<final_json>{"ok": true}</final_json>`)
	case "stderr-head-tail":
		fmt.Fprint(os.Stderr, "stderr-head-"+strings.Repeat("m", 5000)+"-stderr-tail")
		fmt.Print(`<final_json>{"ok": true}</final_json>`)
	case "close-stdin":
		_ = os.Stdin.Close()
		os.Exit(7)
	case "quiet":
		fmt.Print(`<final_json>{"status":"complete"}</final_json>`)
		time.Sleep(5 * time.Second)
	case "spawn-child":
		cmd := exec.Command(os.Args[0], "-test.run=TestHelperProcess", "--", "child-ignore", args[1])
		cmd.Env = helperEnv()
		if err := cmd.Start(); err != nil {
			panic(err)
		}
		deadline := time.Now().Add(time.Second)
		for time.Now().Before(deadline) {
			if _, err := os.Stat(args[1]); err == nil {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
		time.Sleep(10 * time.Second)
	case "child-ignore":
		signalIgnoreTerm()
		if err := os.WriteFile(args[1], []byte(fmt.Sprintf("%d\n", os.Getpid())), 0o644); err != nil {
			panic(err)
		}
		time.Sleep(30 * time.Second)
	default:
		os.Exit(2)
	}
	os.Exit(0)
}

func signalIgnoreTerm() {
	signal.Ignore(syscall.SIGTERM)
}
