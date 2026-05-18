//go:build !unix

package buildworkspace

func processAlive(pid int) (alive bool, known bool) {
	if pid <= 0 {
		return false, false
	}
	return true, false
}
