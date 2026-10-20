"""Test actual GNOME GSettings CLI writes against an isolated keyfile backend.

Never use the live desktop's GSettings/DConf, display, or session bus.
Run: /usr/bin/python3 -B tests/test_gsettings_keyfile.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(env: dict[str, str], *args: str) -> dict:
    proc = subprocess.run([sys.executable, "-m", "appearance_studio", *args],
                          env=env, cwd=ROOT, capture_output=True, text=True,
                          timeout=10)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def run() -> None:
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings executable is required for actual-keyfile regression")
    with tempfile.TemporaryDirectory(prefix="core-keyfile-test-") as td:
        root = Path(td)
        for directory in ("home", "config", "data", "state", "runtime"):
            (root / directory).mkdir()
        (root / "runtime").chmod(0o700)
        env = dict(os.environ)
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                    "WAYLAND_SOCKET", "GDK_DISPLAY"):
            env.pop(key, None)
        env.update({
            "HOME": str(root / "home"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "GSETTINGS_BACKEND": "keyfile",
            "APPEARANCE_STUDIO_ROOT": str(ROOT / "share" / "appearance-studio"),
            "PYTHONPATH": str(ROOT / "src"),
        })
        schemas = subprocess.run(
            ["gsettings", "list-schemas"], env=env, capture_output=True,
            text=True, timeout=5)
        assert schemas.returncode == 0, schemas.stderr
        for schema in ("org.gnome.desktop.interface", "org.gnome.desktop.sound",
                       "org.gnome.desktop.background"):
            assert schema in schemas.stdout.splitlines(), f"Missing schema {schema}"
        initial = invoke(env, "status")
        assert initial["theme_count"] == 1
        assert initial["theme_ids"] == ["studio-default"]

        dark = invoke(env, "apply", "studio-default", "--mode", "dark")
        assert dark["write_count"] > 0
        state = invoke(env, "status")["current"]
        assert state["mode"] == "dark"
        assert state["gtk"] == "'Yaru-dark'"
        assert state["wallpaper"].startswith("'file://")
        assert state["wallpaper"] == state["wallpaper_dark"]
        assert invoke(env, "apply", "studio-default", "--mode", "dark")["write_count"] == 0

        light = invoke(env, "apply", "studio-default", "--mode", "light")
        assert light["write_count"] > 0
        state = invoke(env, "status")["current"]
        assert state["mode"] == "light"
        assert state["gtk"] == "'Yaru'"
        receipt = root / "state" / "appearance-studio" / "last-apply.json"
        receipt_before = receipt.read_bytes()

        # Real keyfile GSettings writes followed by a deliberate error.
        # The engine must roll back both the changed GNOME keys and its receipt.
        injected = r'''
from pathlib import Path
from appearance_studio import engine
from appearance_studio import settings as gs

before = engine.current()
real = gs.set_if_changed
count = 0
def broken(schema, key, value):
    global count
    count += 1
    if count == 3:
        raise gs.SettingsError("injected after earlier real keyfile writes")
    return real(schema, key, value)
gs.set_if_changed = broken
try:
    try:
        engine.apply("studio-default", "dark")
        raise AssertionError("expected transaction rejection")
    except engine.ApplyError as exc:
        assert "rolled back" in str(exc), str(exc)
finally:
    gs.set_if_changed = real
assert engine.current() == before, (engine.current(), before)
print("GSETTINGS_KEYFILE_ACTUAL_WRITE_ROLLBACK_PASS")
'''
        proc = subprocess.run([sys.executable, "-c", injected], env=env,
                              cwd=ROOT, capture_output=True, text=True, timeout=12)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "GSETTINGS_KEYFILE_ACTUAL_WRITE_ROLLBACK_PASS" in proc.stdout
        assert invoke(env, "status")["current"] == state
        assert receipt.read_bytes() == receipt_before
        assert invoke(env, "apply", "studio-default", "--mode", "light")["write_count"] == 0

        keyfile = root / "config" / "glib-2.0" / "settings" / "keyfile"
        assert keyfile.is_file(), "GSettings writes did not use isolated keyfile"
        print("GSETTINGS_KEYFILE_DARK_LIGHT_NOOP_PASS")
        print("GSETTINGS_KEYFILE_ACTUAL_WRITE_ROLLBACK_PASS")


if __name__ == "__main__":
    run()
