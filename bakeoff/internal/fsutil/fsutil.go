package fsutil

import (
	"crypto/rand"
	"encoding/hex"
	"os"
)

func FileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func FileSize(path string) (int64, bool) {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return 0, false
	}
	return info.Size(), true
}

func RandomSuffix() string {
	var data [2]byte
	if _, err := rand.Read(data[:]); err != nil {
		return "0000"
	}
	return hex.EncodeToString(data[:])
}
