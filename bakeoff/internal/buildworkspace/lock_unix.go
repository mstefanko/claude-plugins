//go:build unix

package buildworkspace

import "syscall"

func processAlive(pid int) (alive bool, known bool) {
	if pid <= 0 {
		return false, false
	}
	err := syscall.Kill(pid, 0)
	switch err {
	case nil, syscall.EPERM:
		return true, true
	case syscall.ESRCH:
		return false, true
	default:
		return true, false
	}
}
