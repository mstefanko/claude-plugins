package fsutil

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFileHelpers(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "file.txt")
	if err := os.WriteFile(path, []byte("abc"), 0o600); err != nil {
		t.Fatal(err)
	}
	if !FileExists(path) || FileExists(dir) || FileExists(filepath.Join(dir, "missing")) {
		t.Fatalf("FileExists returned an unexpected value")
	}
	size, ok := FileSize(path)
	if !ok || size != 3 {
		t.Fatalf("FileSize = %d, %t", size, ok)
	}
	if got := RandomSuffix(); len(got) != 4 {
		t.Fatalf("RandomSuffix length = %d", len(got))
	}
}
