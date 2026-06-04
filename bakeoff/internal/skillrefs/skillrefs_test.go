package skillrefs

import (
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
)

func TestSkillLocalReferencesExist(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
	skillFiles, err := filepath.Glob(filepath.Join(root, "skills", "*", "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	re := regexp.MustCompile("`(references/[^`]+)`")
	for _, skillFile := range skillFiles {
		data, err := os.ReadFile(skillFile)
		if err != nil {
			t.Fatal(err)
		}
		for _, match := range re.FindAllStringSubmatch(string(data), -1) {
			referencePath := filepath.Join(filepath.Dir(skillFile), filepath.FromSlash(match[1]))
			if _, err := os.Stat(referencePath); err != nil {
				t.Fatalf("%s references missing %s", skillFile, match[1])
			}
		}
	}
}

func TestBakeoffRunSkillDocumentsPlanReviewRouting(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
	data, err := os.ReadFile(filepath.Join(root, "skills", "bakeoff-run", "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	required := []string{
		`facet.id: "plan-review"`,
		`Plan-vs-diff disambiguation`,
		`review this plan`,
		"`type: \"gather\"` plus `facet.id: \"plan-review\"`",
		`For plan-review requests`,
		`generated code-review diff context`,
		`Do not enable source mutations or build drafting from a plan-review request.`,
	}
	for _, want := range required {
		if !strings.Contains(text, want) {
			t.Fatalf("bakeoff-run skill missing plan-review routing guard %q", want)
		}
	}
}
