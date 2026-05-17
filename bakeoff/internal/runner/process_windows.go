//go:build windows

package runner

import (
	"os"
	"os/exec"
)

func configureProcessGroup(cmd *exec.Cmd) {}

func terminateProcessGroup(process *os.Process) error {
	if process == nil {
		return nil
	}
	return process.Kill()
}

func killProcessGroup(process *os.Process) error {
	if process == nil {
		return nil
	}
	return process.Kill()
}

func processExitCode(state *os.ProcessState) *int {
	if state == nil {
		return nil
	}
	code := state.ExitCode()
	return &code
}
