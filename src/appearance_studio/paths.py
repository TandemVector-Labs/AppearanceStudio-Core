from __future__ import annotations
from pathlib import Path
import os

APP_ID = "io.appearancestudio.Studio"
PRODUCT_NAME = "Appearance Studio"

def home() -> Path:
    return Path.home()

def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", home() / ".local/share")).expanduser()

def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", home() / ".config")).expanduser()

def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", home() / ".local/state")).expanduser()

def cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", home() / ".cache")).expanduser()

def install_root() -> Path:
    explicit = os.environ.get("APPEARANCE_STUDIO_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (data_home() / "appearance-studio").resolve()

def pack_roots() -> tuple[Path, ...]:
    roots = [install_root() / "packs", data_home() / "appearance-studio/packs"]
    out, seen = [], set()
    for raw in roots:
        p = raw.resolve()
        if p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)

def runtime_config() -> Path:
    return config_home() / "appearance-studio"

def runtime_state() -> Path:
    return state_home() / "appearance-studio"
