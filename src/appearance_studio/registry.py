from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib, json, re

ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
MAX_MANIFEST = 512 * 1024

class PackError(ValueError):
    pass

def need(ok: bool, message: str) -> None:
    if not ok:
        raise PackError(message)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_relative(root: Path, value: str) -> Path:
    need(isinstance(value, str) and value and len(value) < 512, "invalid relative path")
    need(chr(0) not in value and "\\" not in value, "unsafe relative path")
    rel = Path(value)
    need(not rel.is_absolute() and ".." not in rel.parts, "unsafe relative path")
    path = (root / rel).resolve()
    need(path.is_relative_to(root.resolve()), "path escapes pack")
    return path

@dataclass(frozen=True)
class Theme:
    pack_id: str
    id: str
    name: str
    dark_theme: str
    light_theme: str
    icon_theme: str
    cursor_theme: str
    sound_theme: str
    wallpaper: Path
    accent: str
    accent2: str
    background: str
    foreground: str

@dataclass(frozen=True)
class Pack:
    root: Path
    id: str
    name: str
    version: str
    license: str
    public_distribution_approved: bool
    themes: tuple[Theme, ...]

def load_pack(root: Path) -> Pack:
    root = root.resolve()
    manifest = root / "manifest.json"
    need(manifest.is_file() and manifest.stat().st_size <= MAX_MANIFEST, "pack manifest missing or too large")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackError("invalid pack manifest") from exc
    need(data.get("schema") == 2, "unsupported pack schema")
    pack_id = data.get("id")
    need(isinstance(pack_id, str) and bool(ID.fullmatch(pack_id)), "invalid pack id")
    name = data.get("name")
    need(isinstance(name, str) and 1 <= len(name) <= 120, "invalid pack name")
    version = data.get("version")
    need(isinstance(version, str) and 1 <= len(version) <= 40, "invalid pack version")
    license_name = data.get("license")
    need(isinstance(license_name, str) and 1 <= len(license_name) <= 120, "pack license required")
    need(type(data.get("public_distribution_approved")) is bool, "public distribution approval flag required")
    rows = data.get("themes")
    need(isinstance(rows, list) and 1 <= len(rows) <= 64, "invalid theme list")
    themes, seen = [], set()
    for row in rows:
        need(isinstance(row, dict), "theme entry must be an object")
        theme_id = row.get("id")
        need(isinstance(theme_id, str) and bool(ID.fullmatch(theme_id)) and theme_id not in seen, "invalid or duplicate theme id")
        seen.add(theme_id)
        theme_name = row.get("name")
        need(isinstance(theme_name, str) and 1 <= len(theme_name) <= 120, "invalid theme name")
        assets = row.get("assets")
        need(isinstance(assets, dict), "theme assets missing")
        names = {}
        for key in ("dark_theme", "light_theme", "icon_theme", "cursor_theme", "sound_theme"):
            value = assets.get(key)
            need(isinstance(value, str) and bool(NAME.fullmatch(value)), "invalid " + key)
            names[key] = value
        wallpaper = safe_relative(root, assets.get("wallpaper", ""))
        need(wallpaper.is_file(), "wallpaper missing")
        expected = assets.get("wallpaper_sha256")
        need(isinstance(expected, str) and len(expected) == 64, "wallpaper hash missing")
        need(sha256(wallpaper) == expected, "wallpaper hash mismatch")
        colors = row.get("colors")
        need(isinstance(colors, dict), "theme colors missing")
        color_values = {}
        for key in ("accent", "accent2", "background", "foreground"):
            value = colors.get(key)
            need(isinstance(value, str) and bool(HEX.fullmatch(value)), "invalid color " + key)
            color_values[key] = value
        themes.append(Theme(pack_id=pack_id, id=theme_id, name=theme_name, wallpaper=wallpaper, **names, **color_values))
    return Pack(root=root, id=pack_id, name=name, version=version, license=license_name, public_distribution_approved=data["public_distribution_approved"], themes=tuple(themes))

def discover(roots) -> tuple[Pack, ...]:
    packs, seen = [], set()
    for base in roots:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or not (child / "manifest.json").is_file():
                continue
            pack = load_pack(child)
            need(pack.id not in seen, "duplicate pack id: " + pack.id)
            seen.add(pack.id)
            packs.append(pack)
    return tuple(packs)
