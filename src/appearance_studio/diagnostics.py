from __future__ import annotations
from pathlib import Path
import shutil, importlib.util
from .paths import pack_roots
from .registry import discover, PackError

def _name_exists(name, roots):
    return any((root/name).exists() for root in roots)

def report():
    result={"pass":True,"checks":{},"warnings":[]}
    for cmd in ("gsettings","python3"):
        ok=shutil.which(cmd) is not None
        result["checks"]["command_"+cmd]=ok
        result["pass"] &= ok
    result["checks"]["python_gi_available"]=importlib.util.find_spec("gi") is not None
    result["checks"]["python_dbus_available"]=importlib.util.find_spec("dbus") is not None
    if not result["checks"]["python_gi_available"]:
        result["warnings"].append({"dependency":"python3-gi","impact":"Graphical interface unavailable; command-line core remains usable."})
    if not result["checks"]["python_dbus_available"]:
        result["warnings"].append({"dependency":"python3-dbus","impact":"Panel system monitor unavailable; theme core remains usable."})
    try:
        packs=discover(pack_roots())
        result["checks"]["packs_valid"]=bool(packs)
        result["pack_count"]=len(packs)
        themes=[t for p in packs for t in p.themes]
        result["theme_count"]=len(themes)
        result["pass"] &= bool(packs and themes)
    except Exception as exc:
        packs=()
        themes=[]
        result["checks"]["packs_valid"]=False
        result["errors"]=[str(exc)]
        result["pass"]=False
    theme_roots=[Path.home()/".local/share/themes",Path("/usr/local/share/themes"),Path("/usr/share/themes")]
    icon_roots=[Path.home()/".local/share/icons",Path.home()/".icons",Path("/usr/local/share/icons"),Path("/usr/share/icons")]
    sound_roots=[Path.home()/".local/share/sounds",Path("/usr/local/share/sounds"),Path("/usr/share/sounds")]
    for theme in themes:
        missing=[]
        for label,name,roots in (
            ("dark_theme",theme.dark_theme,theme_roots),
            ("light_theme",theme.light_theme,theme_roots),
            ("icon_theme",theme.icon_theme,icon_roots),
            ("cursor_theme",theme.cursor_theme,icon_roots),
            ("sound_theme",theme.sound_theme,sound_roots),
        ):
            if not _name_exists(name,roots):
                missing.append(label+":"+name)
        if missing:
            result["warnings"].append({"theme":theme.id,"missing_optional_or_system_assets":missing})
    return result
