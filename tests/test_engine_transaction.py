from __future__ import annotations
import importlib, os, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["APPEARANCE_STUDIO_ROOT"] = str(ROOT / "share/appearance-studio")
_tmp = tempfile.TemporaryDirectory(prefix="appearance-studio-test-")
os.environ["XDG_STATE_HOME"] = str(Path(_tmp.name) / "state")
os.environ["XDG_CONFIG_HOME"] = str(Path(_tmp.name) / "config")

import appearance_studio.engine as engine

def run():
    state = {
        ("org.gnome.desktop.interface","color-scheme"): "'default'",
        ("org.gnome.desktop.interface","gtk-theme"): "'Yaru'",
        ("org.gnome.desktop.interface","icon-theme"): "'Yaru'",
        ("org.gnome.desktop.interface","cursor-theme"): "'Yaru'",
        ("org.gnome.desktop.sound","theme-name"): "'Yaru'",
        ("org.gnome.desktop.background","picture-uri"): "''",
        ("org.gnome.desktop.background","picture-uri-dark"): "''",
    }
    writes = []
    def get(schema,key):
        return state[(schema,key)]
    def set_if_changed(schema,key,value):
        key2=(schema,key)
        if isinstance(value,bool):
            raw="true" if value else "false"
        else:
            raw=str(value)
        target=raw if raw in ("true","false") else "'" + raw.strip("'") + "'"
        if state[key2] == target:
            return False
        state[key2]=target
        writes.append((schema,key,target))
        return True
    engine.gs.get=get
    engine.gs.set_if_changed=set_if_changed

    first=engine.apply("studio-default","dark")
    assert first["write_count"] >= 2
    assert state[("org.gnome.desktop.interface","gtk-theme")] == "'Yaru-dark'"
    writes.clear()
    second=engine.apply("studio-default","dark")
    assert second["write_count"] == 0
    assert writes == []

    # Fault injection: fail after one changed key, then verify exact rollback.
    engine.apply("studio-default","light")
    baseline=dict(state)
    calls={"n":0}
    def failing_set(schema,key,value):
        calls["n"] += 1
        if key == "icon-theme":
            raise RuntimeError("injected failure")
        return set_if_changed(schema,key,value)
    engine.gs.set_if_changed=failing_set
    try:
        engine.apply("studio-default","dark")
        raise AssertionError("fault injection unexpectedly committed")
    except engine.ApplyError as exc:
        assert "rolled back" in str(exc) or "rollback errors" in str(exc)
    assert state == baseline, (state,baseline)
    print("TRANSACTION_NOOP_ROLLBACK_PASS")

if __name__ == "__main__":
    run()
