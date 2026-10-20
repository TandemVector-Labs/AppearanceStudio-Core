"""Refuse cross-install service-name collisions before activation or removal.

All write operations take place in temporary XDG directories. systemctl is a
deliberate fake to reproduce a separate live user manager's FragmentPath.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    if os.geteuid() == 0:
        print("CORE_MANAGER_UNIT_OWNERSHIP_SKIPPED_ROOT")
        return
    with tempfile.TemporaryDirectory(prefix="core-unit-ownership-") as td:
        root = Path(td)
        home = root / "home"
        home.mkdir()
        fake = root / "bin"
        fake.mkdir()
        ctl = fake / "systemctl"
        ctl.write_text(
            '#!/bin/sh\n'
            'if [ "$2" = show ]; then\n'
            '  if [ "$3" = appearance-studio-theme-monitor.service ]; then\n'
            '    printf "%s\\n" "$CORE_FAKE_THEME_FRAGMENT"\n'
            '  else\n'
            '    printf "%s\\n" "$CORE_FAKE_SYSTEM_FRAGMENT"\n'
            '  fi\n'
            '  exit 0\n'
            'fi\n'
            'printf "%s\\n" "$*" >> "$CORE_FAKE_SERVICE_LOG"\n',
            encoding="utf-8")
        ctl.chmod(0o755)
        log = root / "systemctl.log"
        config = root / "config"
        theme = config / "systemd/user/appearance-studio-theme-monitor.service"
        system = config / "systemd/user/appearance-studio-system-monitor.service"
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(config),
            "XDG_STATE_HOME": str(root / "state"),
            "PATH": str(fake) + os.pathsep + os.environ.get("PATH", ""),
            "CORE_FAKE_SERVICE_LOG": str(log),
            "CORE_FAKE_THEME_FRAGMENT": str(root / "different-install" / theme.name),
            "CORE_FAKE_SYSTEM_FRAGMENT": str(system),
        })
        receipt = root / "state" / "appearance-studio" / "install-manifest.json"

        def invoke(script: str, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run([sys.executable, str(ROOT / script), *args],
                                  env=env, cwd=ROOT, capture_output=True,
                                  text=True, timeout=20)

        fresh = invoke("install.py")
        assert fresh.returncode == 0, fresh.stdout + fresh.stderr
        original_receipt = receipt.read_bytes()
        original_theme = theme.read_bytes()
        rejected = invoke("install.py", "--activate")
        assert rejected.returncode != 0
        assert "foreign user-manager unit collision" in rejected.stderr
        assert receipt.read_bytes() == original_receipt
        assert theme.read_bytes() == original_theme
        assert not log.exists(), "foreign units must not receive daemon-reload/enable"

        # Exact owned fragments admit normal explicit activation.
        env["CORE_FAKE_THEME_FRAGMENT"] = str(theme)
        accepted = invoke("install.py", "--activate")
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert json.loads(receipt.read_text())["activate_requested"] is True
        assert "enable --now" in log.read_text()
        baseline_log = log.read_bytes()

        # The other name can independently collide on uninstall.
        env["CORE_FAKE_SYSTEM_FRAGMENT"] = str(root / "different-install" / system.name)
        rejected = invoke("uninstall.py")
        assert rejected.returncode != 0
        assert "Foreign user-manager unit collision" in rejected.stderr
        assert receipt.is_file() and theme.is_file() and system.is_file()
        assert log.read_bytes() == baseline_log
        env["CORE_FAKE_SYSTEM_FRAGMENT"] = str(system)
        removed = invoke("uninstall.py")
        assert removed.returncode == 0, removed.stdout + removed.stderr
        assert "disable --now" in log.read_text()
        assert not receipt.exists()
        print("CORE_FOREIGN_MANAGER_UNIT_COLLISION_GUARD_PASS")


if __name__ == "__main__":
    run()
