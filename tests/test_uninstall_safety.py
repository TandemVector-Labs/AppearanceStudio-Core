"""Uninstall safety regression: isolated XDG locations and fake service manager only."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run():
    if os.geteuid() == 0:
        print("CORE_UNINSTALL_SAFETY_SKIPPED_ROOT")
        return
    with tempfile.TemporaryDirectory(prefix="core-uninstall-safety-") as td:
        t = Path(td)
        home = t / "home"
        home.mkdir()
        fakebin = t / "bin"
        fakebin.mkdir()
        ctl = fakebin / "systemctl"
        ctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CORE_SERVICE_LOG"\n',
                       encoding="utf-8")
        ctl.chmod(0o755)
        log = t / "service-events.log"
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(t / "data"),
            "XDG_CONFIG_HOME": str(t / "config"),
            "XDG_STATE_HOME": str(t / "state"),
            "CORE_SERVICE_LOG": str(log),
            "PATH": str(fakebin) + os.pathsep + env.get("PATH", ""),
        })
        def execute(filename, *args, custom_env=None):
            return subprocess.run([sys.executable, str(ROOT / filename), *args],
                                  cwd=ROOT, env=custom_env or env,
                                  text=True, capture_output=True, timeout=15)

        first = execute("install.py", "--activate")
        assert first.returncode == 0, first.stdout + first.stderr
        receipt = t / "state" / "appearance-studio" / "install-manifest.json"
        owned = t / "data" / "appearance-studio" / "python"
        assert receipt.is_file() and owned.is_dir()
        assert json.loads(receipt.read_text())["activate_requested"] is True
        settings = t / "config" / "appearance-studio" / "preferences.json"
        settings.parent.mkdir(parents=True)
        settings.write_bytes(b"personal-settings")
        extra = t / "data" / "appearance-studio" / "packs" / "personal" / "contents.txt"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"personal-pack")

        # The prior installer must not remove a Core installation while a
        # pending journal or incomplete preparation exists.
        state = t / "state" / "appearance-studio"
        for name in ("core-install-pending", ".core-install-preparing"):
            directory = state / name
            directory.mkdir()
            blocked = execute("uninstall.py")
            assert blocked.returncode != 0
            assert "Unfinished Core install/recovery" in blocked.stderr
            assert receipt.is_file() and owned.is_dir()
            directory.rmdir()

        # Never follow a linked HOME/.local parent that could reach a
        # different installation. Restore the original directory afterward.
        local = home / ".local"
        parked = home / ".local-original"
        assert local.is_dir()
        local.rename(parked)
        local.symlink_to(parked, target_is_directory=True)
        try:
            blocked = execute("uninstall.py")
            assert blocked.returncode != 0
            assert "linked/unsafe" in blocked.stderr
            assert receipt.is_file() and owned.is_dir()
        finally:
            local.unlink()
            parked.rename(local)

        # If a prior --activate was requested, removing files while
        # systemctl cannot be executed would orphan active service units.
        without_systemctl = dict(env, PATH=str(t / "missing-programs"))
        blocked = execute("uninstall.py", custom_env=without_systemctl)
        assert blocked.returncode != 0
        assert "Cannot locate systemctl" in blocked.stderr
        assert receipt.is_file() and owned.is_dir()

        # A second process must not uninstall while installer lock is held.
        lock = state / ".core-install.lock"
        with lock.open("a+") as fd:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
            process = subprocess.Popen([sys.executable, str(ROOT / "uninstall.py")],
                                       cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(0.15)
                assert process.poll() is None, "uninstall ignored exclusive install lock"
                assert receipt.is_file() and owned.is_dir()
            finally:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stdout + stderr

        assert not receipt.exists() and not owned.exists()
        assert settings.read_bytes() == b"personal-settings"
        assert extra.read_bytes() == b"personal-pack"
        assert "disable --now appearance-studio-theme-monitor.service" in log.read_text()
        print("CORE_UNINSTALL_LOCK_PENDING_SYMLINK_SERVICE_SAFETY_PASS")


if __name__ == "__main__":
    run()
