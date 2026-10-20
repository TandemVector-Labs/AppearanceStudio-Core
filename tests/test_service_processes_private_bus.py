"""Start actual Core monitor processes on a disposable private D-Bus session.

This is a process-liveness canary, NOT verification of service installation,
systemd user-manager activation, GUI icon visibility, or long-term uptime.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    assert shutil.which("dbus-run-session"), "isolated dbus-run-session is required"
    assert shutil.which("gsettings"), "isolated gsettings is required"
    with tempfile.TemporaryDirectory(prefix="appearance-private-bus-") as td:
        root = Path(td)
        for name in ("home", "data", "config", "state", "runtime"):
            (root / name).mkdir()
        (root / "runtime").chmod(0o700)
        env = dict(os.environ)
        for key in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY",
                    "WAYLAND_SOCKET", "GDK_DISPLAY"):
            env.pop(key, None)
        env.update({
            "HOME": str(root / "home"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "GSETTINGS_BACKEND": "keyfile",
            "APPEARANCE_STUDIO_ROOT": str(ROOT / "share" / "appearance-studio"),
            "PYTHONPATH": str(ROOT / "src"),
        })
        # The private bus must outlive the monitor being stopped.
        # Killing the entire process group first terminates dbus-daemon
        # before dbus-python can release BusName on normal SIGTERM.
        controlled_stop = r'''
import subprocess,sys,time
name=sys.argv[1]
child=subprocess.Popen(
    [sys.executable,"-B","-m","appearance_studio",name],
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
    time.sleep(1.0)
    assert child.poll() is None, f"{name} exited prematurely"
finally:
    if child.poll() is None:
        child.terminate()
    output,errors=child.communicate(timeout=4)
assert "Traceback" not in errors, errors
if name=="system-monitor":
    assert "APPEARANCE_STUDIO_MONITOR_READY" in output, output
print("PRIVATE_DBUS_"+name.upper().replace("-","_")+"_STARTUP_PASS")
'''
        for name in ("monitor", "system-monitor"):
            proc = subprocess.run(
                ["dbus-run-session", "--", sys.executable, "-B",
                 "-c", controlled_stop, name],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=9,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
            assert "Traceback" not in proc.stderr, proc.stderr
            assert "PRIVATE_DBUS_" + name.upper().replace("-", "_") + "_STARTUP_PASS" in proc.stdout
            print("PRIVATE_DBUS_" + name.upper().replace("-", "_") + "_STARTUP_PASS")
        assert not (root / "config" / "dconf").exists()
        print("PRIVATE_DBUS_MONITOR_PROCESS_LIVENESS_PASS")


if __name__ == "__main__":
    run()
