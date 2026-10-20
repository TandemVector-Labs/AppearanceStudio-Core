"""Manual opt-in canary under the REAL logged-in user systemd manager.

Only short-lived, uniquely named TRANSIENT units are created. This does not
install/enable the official Appearance Studio units and does not attach to the
active user's session bus or modify GNOME/dconf. It does not replace an
attended systemd user-unit integration or desktop visual acceptance test.

Run on an authorized desktop-user host:
  python3 -B tests/test_systemd_user_canary.py --run-transient
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_PREFIX = "as-core-canary-"


def command(args: list[str], *, timeout: int = 6) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def start_and_stop(kind: str, env: dict[str, str], state_dir: Path) -> None:
    unit = UNIT_PREFIX + kind.replace("_", "-") + "-" + secrets.token_hex(5) + ".service"
    cmd = [
        "systemd-run", "--user", "--collect", "--unit=" + unit,
        "--property=RuntimeMaxSec=12s",
        "--property=WorkingDirectory=" + str(ROOT),
    ]
    for key in (
        "HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME",
        "XDG_RUNTIME_DIR", "GSETTINGS_BACKEND",
        "PYTHONPATH", "APPEARANCE_STUDIO_ROOT",
    ):
        cmd.append("--setenv=" + key + "=" + env[key])
    cmd += [
        "dbus-run-session", "--", sys.executable, "-B",
        "-m", "appearance_studio", kind.replace("_", "-"),
    ]
    before = command(["systemctl", "--user", "show", unit, "-p", "LoadState", "--value"])
    assert before.stdout.strip() != "loaded", "Unexpected unit collision"
    launched = command(cmd)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    try:
        active = False
        for _ in range(15):
            result = command(["systemctl", "--user", "is-active", unit])
            if result.stdout.strip() == "active":
                active = True
                break
            time.sleep(0.1)
        assert active, f"{unit}: transient unit did not become active"
        if kind == "system_monitor":
            status = state_dir / "appearance-studio" / "system-monitor-indicator.json"
            for _ in range(15):
                if status.is_file():
                    break
                time.sleep(0.1)
            assert status.is_file(), "system monitor did not produce isolated state"
            payload = json.loads(status.read_text(encoding="utf-8"))
            assert payload["build_id"] == "APPEARANCE-STUDIO-MONITOR-1"
            assert "updated_at" in payload
        print("REAL_SYSTEMD_TRANSIENT_" + kind.upper() + "_ACTIVE_PASS")
    finally:
        stopped = command(["systemctl", "--user", "stop", unit], timeout=8)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        result = command(["systemctl", "--user", "show", unit, "-p", "ActiveState", "--value"])
        assert result.stdout.strip() != "active", unit
        print("REAL_SYSTEMD_TRANSIENT_" + kind.upper() + "_CLEAN_STOP_PASS")


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-transient", action="store_true")
    args = parser.parse_args()
    if not args.run_transient:
        raise SystemExit("Opt-in required: --run-transient")
    if os.geteuid() == 0:
        raise SystemExit("Refusing root. Execute as ordinary desktop user.")
    for tool in ("systemctl", "systemd-run", "dbus-run-session"):
        if shutil.which(tool) is None:
            raise SystemExit("Missing " + tool)
    health = command(["systemctl", "--user", "is-system-running"])
    if health.stdout.strip() not in ("running", "degraded"):
        raise SystemExit("No healthy existing user systemd manager")
    with tempfile.TemporaryDirectory(prefix="appearance-systemd-user-canary-") as td:
        root = Path(td)
        for name in ("home", "data", "config", "state", "runtime"):
            (root / name).mkdir()
        (root / "runtime").chmod(0o700)
        env = {
            "HOME": str(root / "home"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "GSETTINGS_BACKEND": "keyfile",
            "PYTHONPATH": str(ROOT / "src"),
            "APPEARANCE_STUDIO_ROOT": str(ROOT / "share" / "appearance-studio"),
        }
        start_and_stop("monitor", env, root / "state")
        start_and_stop("system_monitor", env, root / "state")
        assert not (root / "config" / "dconf").exists()
        assert not (root / "config" / "systemd").exists()
        print("REAL_SYSTEMD_USER_TRANSIENT_CORE_MONITORS_PASS")


if __name__ == "__main__":
    run()
