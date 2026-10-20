"""Verify real systemctl offline enable/disable in a disposable filesystem root.

This intentionally NEVER accesses the logged-in user's systemd manager.
No --user daemon-reload, no active service start, no host-wide units changed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = (
    "appearance-studio-theme-monitor.service",
    "appearance-studio-system-monitor.service",
)


def call(root: Path, *args: str) -> None:
    proc = subprocess.run(
        ["systemctl", "--global", "--root=" + str(root), *args],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def run() -> None:
    assert shutil.which("systemctl"), "systemctl is required"
    with tempfile.TemporaryDirectory(prefix="appearance-systemd-offline-") as td:
        root = Path(td)
        units = root / "etc" / "systemd" / "user"
        units.mkdir(parents=True)
        original = {}
        for name in UNITS:
            data = (ROOT / "share" / "systemd" / "user" / name).read_bytes()
            assert b"WantedBy=graphical-session.target" in data
            (units / name).write_bytes(data)
            original[name] = data
        (units / "graphical-session.target").write_text(
            "[Unit]\nDescription=Disposable graphical session target\n",
            encoding="utf-8",
        )
        call(root, "enable", *UNITS)
        wants = units / "graphical-session.target.wants"
        assert wants.is_dir()
        for name in UNITS:
            link = wants / name
            assert link.is_symlink(), f"unit not enabled: {name}"
            assert link.readlink().as_posix() == "/etc/systemd/user/" + name
        call(root, "disable", *UNITS)
        for name in UNITS:
            assert not (wants / name).exists()
            assert (units / name).read_bytes() == original[name]
        print("SYSTEMCTL_STAGED_UNIT_ENABLE_DISABLE_PASS")


if __name__ == "__main__":
    run()
