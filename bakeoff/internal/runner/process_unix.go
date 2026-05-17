//go:build !windows

package runner

import (
	"os"
	"os/exec"
	"syscall"
)

func configureProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

func terminateProcessGroup(process *os.Process) error {
	if process == nil {
		return nil
	}
	if err := syscall.Kill(-process.Pid, syscall.SIGTERM); err != nil {
		if err == syscall.ESRCH {
			return nil
		}
		return process.Signal(syscall.SIGTERM)
	}
	return nil
}

func killProcessGroup(process *os.Process) error {
	if process == nil {
		return nil
	}
	if err := syscall.Kill(-process.Pid, syscall.SIGKILL); err != nil {
		if err == syscall.ESRCH {
			return nil
		}
		return process.Kill()
	}
	return nil
}

func processExitCode(state *os.ProcessState) *int {
	if state == nil {
		return nil
	}
	if status, ok := state.Sys().(syscall.WaitStatus); ok {
		if status.Signaled() {
			code := -int(status.Signal())
			return &code
		}
		if status.Exited() {
			code := status.ExitStatus()
			return &code
		}
	}
	code := state.ExitCode()
	return &code
}
