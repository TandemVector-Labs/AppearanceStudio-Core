"""Optional GTK4/Libadwaita GUI smoke on isolated local-only Broadway display.

Run: python3 -B tests/test_ui_broadway.py

No login session, GNOME Shell extensions, gsettings, user files or internet
are changed. Requires python3-gi, GTK 4, Libadwaita and gtk4-broadwayd.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def child() -> int:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw, GLib
    from appearance_studio import ui

    # Reading real desktop state is unnecessary for a UI structure test.
    # Use a read-only stand-in and enforce GSettings memory backend.
    assert os.environ["GSETTINGS_BACKEND"] == "memory"
    assert os.environ["GDK_BACKEND"] == "broadway"
    assert "DISPLAY" not in os.environ
    assert "WAYLAND_DISPLAY" not in os.environ
    assert "DBUS_SESSION_BUS_ADDRESS" not in os.environ

    ui.status = lambda: {"current": {
        "gtk": "sandbox", "icons": "sandbox", "cursor": "sandbox"
    }}
    themes = ui.all_themes()
    assert len(themes) == 1, f"Expected exactly one public Core theme: {list(themes)}"
    app = ui.StudioApplication()
    assert app.register(None)
    app.activate()
    for _ in range(15):
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(0.02)

    window = app.props.active_window
    assert window is not None
    assert isinstance(window, Adw.ApplicationWindow)
    assert window.get_title() == "Appearance Studio"
    pages = window.stack.get_pages()
    assert pages.get_n_items() == 4
    assert [pages.get_item(i).get_name() for i in range(4)] == [
        "themes", "packs", "diagnostics", "about"
    ]
    assert [pages.get_item(i).get_title() for i in range(4)] == [
        "Themes", "Packs", "Diagnostics", "About"
    ]
    assert window.get_surface() is not None, "Window surface not created"
    print("BROADWAY_UI_FOUR_PAGES_RENDERED_PASS")
    window.close()
    app.quit()
    return 0


def run() -> int:
    daemon = shutil.which("gtk4-broadwayd")
    if daemon is None:
        raise RuntimeError("gtk4-broadwayd is required for the optional isolated GUI test")
    with tempfile.TemporaryDirectory(prefix="appearance-core-ui-broadway-") as td:
        root = Path(td)
        for name in ("home", "data", "config", "state", "runtime"):
            (root / name).mkdir()
        (root / "runtime").chmod(0o700)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        env = dict(os.environ)
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                    "WAYLAND_SOCKET", "GDK_DISPLAY"):
            env.pop(key, None)
        env.update({
            "HOME": str(root / "home"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "GSETTINGS_BACKEND": "memory",
            "GDK_BACKEND": "broadway",
            "BROADWAY_DISPLAY": ":93",
            "APPEARANCE_STUDIO_ROOT": str(ROOT / "share" / "appearance-studio"),
            "PYTHONPATH": str(ROOT / "src"),
        })
        server = subprocess.Popen([
            daemon, "--address=127.0.0.1", "--port=" + str(port), ":93"
        ], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.25)
            assert server.poll() is None, "Broadway server failed to start"
            proc = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--child"],
                env=env, capture_output=True, text=True, timeout=12
            )
            if proc.returncode:
                raise AssertionError("isolated GTK UI failed\n" + proc.stdout + proc.stderr)
            assert "BROADWAY_UI_FOUR_PAGES_RENDERED_PASS" in proc.stdout, proc.stdout
            assert "Gtk-WARNING" not in proc.stderr, proc.stderr
            assert "markup" not in proc.stderr.lower(), proc.stderr
            print(proc.stdout.strip())
            print("BROADWAY_GUI_ISOLATED_NO_GTK_WARNING_PASS")
        finally:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(child() if sys.argv[1:] == ["--child"] else run())
