package main

import (
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"testing"
)

func TestPluginCopyFailureRemovesPartialDestination(t *testing.T) {
	if root := os.Getenv("MOUSA_PLUGIN_FAILURE_ROOT"); root != "" {
		signal.Ignore(syscall.SIGXFSZ)
		if err := syscall.Setrlimit(syscall.RLIMIT_FSIZE, &syscall.Rlimit{Cur: 16384, Max: 16384}); err != nil {
			t.Fatal(err)
		}
		if err := pluginCommand(filepath.Join(root, "store.sqlite"), []string{"--out", filepath.Join(root, "plugin"), "--source", "alpha", "--consent-to-share"}); err == nil {
			t.Fatal("packaging unexpectedly succeeded under executable size limit")
		}
		if _, err := os.Stat(filepath.Join(root, "plugin")); !os.IsNotExist(err) {
			t.Fatalf("partial plugin retained: %v", err)
		}
		return
	}
	root := t.TempDir()
	command := exec.Command(os.Args[0], "-test.run=^TestPluginCopyFailureRemovesPartialDestination$")
	command.Env = append(os.Environ(), "MOUSA_PLUGIN_FAILURE_ROOT="+root)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("packaging failure subprocess: %v\n%s", err, output)
	}
}
