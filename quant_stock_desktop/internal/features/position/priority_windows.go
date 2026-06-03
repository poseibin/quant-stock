//go:build windows

package position

import "os/exec"

func applyLowPriority(cmd *exec.Cmd) {}

func lowerPriorityAfterStart(pid int) {}
