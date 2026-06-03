//go:build darwin || linux

package position

import (
	"os/exec"
	"syscall"
)

func applyLowPriority(cmd *exec.Cmd) {
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	cmd.SysProcAttr.Setpgid = true
}

func lowerPriorityAfterStart(pid int) {
	_ = syscall.Setpriority(syscall.PRIO_PROCESS, pid, 10)
}
