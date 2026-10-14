from __future__ import annotations
from pathlib import Path
import fcntl, json, os, tempfile, time
from .paths import pack_roots, runtime_state
from .registry import discover, Theme
from . import settings as gs

class ApplyError(RuntimeError):
    pass

def all_themes():
    rows = {}
    for pack in discover(pack_roots()):
        for theme in pack.themes:
            if theme.id in rows:
                raise ApplyError("duplicate theme id: " + theme.id)
            rows[theme.id] = theme
    return rows

def color_mode():
    raw = gs.get("org.gnome.desktop.interface", "color-scheme")
    return "dark" if "prefer-dark" in raw else "light"

def current():
    return {
        "gtk": gs.get("org.gnome.desktop.interface", "gtk-theme"),
        "icons": gs.get("org.gnome.desktop.interface", "icon-theme"),
        "cursor": gs.get("org.gnome.desktop.interface", "cursor-theme"),
        "sound": gs.get("org.gnome.desktop.sound", "theme-name"),
        "wallpaper": gs.get("org.gnome.desktop.background", "picture-uri"),
        "wallpaper_dark": gs.get("org.gnome.desktop.background", "picture-uri-dark"),
        "mode": color_mode(),
    }

def _atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass

def _theme_uri(theme: Theme):
    return theme.wallpaper.resolve().as_uri()

def plan(theme_id, mode=None):
    themes = all_themes()
    if theme_id not in themes:
        raise ApplyError("unknown theme: " + theme_id)
    theme = themes[theme_id]
    mode = mode or color_mode()
    if mode not in ("dark", "light"):
        raise ApplyError("invalid mode")
    return {
        "theme": theme_id,
        "mode": mode,
        "gtk": theme.dark_theme if mode == "dark" else theme.light_theme,
        "icons": theme.icon_theme,
        "cursor": theme.cursor_theme,
        "sound": theme.sound_theme,
        "wallpaper": _theme_uri(theme),
        "accent": theme.accent,
        "accent2": theme.accent2,
    }

def _restore(before):
    pairs = [
        ("org.gnome.desktop.interface", "color-scheme", "prefer-dark" if before["mode"] == "dark" else "default"),
        ("org.gnome.desktop.interface", "gtk-theme", before["gtk"]),
        ("org.gnome.desktop.interface", "icon-theme", before["icons"]),
        ("org.gnome.desktop.interface", "cursor-theme", before["cursor"]),
        ("org.gnome.desktop.sound", "theme-name", before["sound"]),
        ("org.gnome.desktop.background", "picture-uri", before["wallpaper"]),
        ("org.gnome.desktop.background", "picture-uri-dark", before["wallpaper_dark"]),
    ]
    errors = []
    for schema, key, value in pairs:
        try:
            gs.set_if_changed(schema, key, value)
        except Exception as exc:
            errors.append(f"{schema}:{key}:{exc}")
    return errors

def apply(theme_id, mode=None):
    desired = plan(theme_id, mode)
    state = runtime_state()
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "appearance.lock"
    with lock.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        before = current()
        changed = []
        try:
            requested = [
                ("org.gnome.desktop.interface", "color-scheme", "prefer-dark" if desired["mode"] == "dark" else "default", "color-scheme"),
                ("org.gnome.desktop.interface", "gtk-theme", desired["gtk"], "gtk-theme"),
                ("org.gnome.desktop.interface", "icon-theme", desired["icons"], "icon-theme"),
                ("org.gnome.desktop.interface", "cursor-theme", desired["cursor"], "cursor-theme"),
                ("org.gnome.desktop.sound", "theme-name", desired["sound"], "sound-theme"),
                ("org.gnome.desktop.background", "picture-uri", desired["wallpaper"], "wallpaper"),
                ("org.gnome.desktop.background", "picture-uri-dark", desired["wallpaper"], "wallpaper-dark"),
            ]
            for schema, key, value, label in requested:
                if gs.set_if_changed(schema, key, value):
                    changed.append(label)
            after = current()
            expected = {
                "gtk": "'" + desired["gtk"] + "'",
                "icons": "'" + desired["icons"] + "'",
                "cursor": "'" + desired["cursor"] + "'",
                "sound": "'" + desired["sound"] + "'",
                "wallpaper": "'" + desired["wallpaper"] + "'",
                "wallpaper_dark": "'" + desired["wallpaper"] + "'",
            }
            for key, value in expected.items():
                if after[key] != value:
                    raise ApplyError("post-apply mismatch: " + key)
            receipt = {
                "schema": 1,
                "theme": theme_id,
                "mode": desired["mode"],
                "changed": changed,
                "at_unix": time.time(),
                "write_count": len(changed),
            }
            _atomic_json(state / "last-apply.json", receipt)
            return receipt
        except Exception as original:
            errors = _restore(before)
            if errors:
                raise ApplyError(f"apply failed: {original}; rollback errors: {errors}") from original
            raise ApplyError(f"apply failed and rolled back: {original}") from original
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

def status():
    themes = all_themes()
    return {
        "theme_count": len(themes),
        "theme_ids": sorted(themes),
        "current": current(),
    }
